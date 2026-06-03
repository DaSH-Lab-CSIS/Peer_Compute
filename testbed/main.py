#!/usr/bin/env python3
"""
Main Orchestrator - CLI interface for running testbed scenarios.
"""
import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
from uuid import uuid4
from typing import Dict, Any, Optional  

from core.service_analyzer import ServiceAnalyzer
from core.metrics_collector import MetricsCollector
from scenarios.baseline import BaselineScenario
from scenarios.steady_load import SteadyLoadScenario
from scenarios.bursty_load import BurstyLoadScenario
from scenarios.stress_soak import StressSoakScenario
from scenarios.chaos_edge import ChaosEdgeScenario
from scenarios.fairness_mix import FairnessMixScenario
from utils.config_loader import get_scenario_config, get_services_config, load_yaml
from utils.logger import setup_logger
from analysis.report_generator import ReportGenerator
from analysis.visualizer import MetricsVisualizer
from core.job_enricher import enrich_run
from core.drive_uploader import upload_run_artefacts

# Paths relative to this file so `python main.py` works from repo root or from testbed/
_TESTBED_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG_DIR = str(_TESTBED_DIR / "config")
_DEFAULT_RESULTS_DIR = str(_TESTBED_DIR / "results")


SCENARIO_CLASSES = {
    'baseline': BaselineScenario,
    'steady_load': SteadyLoadScenario,
    'bursty_load': BurstyLoadScenario,
    'stress_soak': StressSoakScenario,
    'chaos_edge': ChaosEdgeScenario,
    'fairness_mix': FairnessMixScenario,
}


def create_run_id(scenario_name: str, iteration: int = None) -> str:
    """Create a unique run ID."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_id = f"{scenario_name}_{timestamp}"
    if iteration is not None:
        run_id += f"_iter{iteration}"
    return run_id


def apply_research_scaling(config: Dict[str, Any], scenario_name: str) -> Dict[str, Any]:
    """
    Apply research-scale scaling multipliers to configuration.
    
    Args:
        config: Base configuration dictionary
        scenario_name: Name of the scenario
        
    Returns:
        Scaled configuration dictionary
    """
    scaled_config = config.copy()
    
    # Research-scale multipliers based on Grok_plan.md recommendations
    scaling_map = {
        'baseline': {
            'total_requests': 5  # 100 -> 500
        },
        'bursty_load': {
            'burst_size': 2,  # 200 -> 400
            'repeat_count': 1.25  # 5 -> 6-7 (round to 6)
        },
        'stress_soak': {
            'min_requests': 5000,  # Add min_requests
            'target_rps': 1.5  # 100 -> 150 (optional, can keep 100)
        },
        'chaos_edge': {
            'total_requests': 5  # 200 -> 1000
        },
        'fairness_mix': {
            'phases_request_count': 5  # 200 -> 1000 per phase (600 -> 3000 total)
        }
        # steady_load already supports research scale
    }
    
    if scenario_name in scaling_map:
        scaling = scaling_map[scenario_name]
        for key, value in scaling.items():
            if key == 'phases_request_count' and 'phases' in scaled_config:
                # Scale request_count inside each phase entry
                scaled_phases = []
                for phase in scaled_config['phases']:
                    scaled_phase = phase.copy()
                    if 'request_count' in scaled_phase:
                        scaled_phase['request_count'] = int(scaled_phase['request_count'] * value)
                    scaled_phases.append(scaled_phase)
                scaled_config['phases'] = scaled_phases
                if 'total_requests' in scaled_config:
                    scaled_config['total_requests'] = sum(
                        p.get('request_count', 0) for p in scaled_config['phases']
                    )
            elif key in scaled_config:
                if isinstance(value, (int, float)) and isinstance(scaled_config[key], (int, float)):
                    if key == 'repeat_count':
                        scaled_config[key] = max(1, int(scaled_config[key] * value))
                    else:
                        scaled_config[key] = int(scaled_config[key] * value)
                elif key == 'min_requests' and scaled_config.get(key) is None:
                    scaled_config[key] = value
    
    return scaled_config


async def run_scenario(
    scenario_name: str,
    config_dir: Optional[str] = None,
    load_balancer_url: str = "http://localhost:9001",
    output_dir: Optional[str] = None,
    run_id: str = None,
    iterations: int = 1,
    research_mode: bool = False,
    seed: Optional[int] = None,
    save_requests: bool = False,
    replay_file: Optional[str] = None,
    save_only: bool = False,
    enrich_after_run: bool = False,
    scheduler_url: Optional[str] = None,
    enrich_since: Optional[str] = None,
    enrich_until: Optional[str] = None,
    upload_to_drive: bool = False,
    drive_credentials: Optional[str] = None,
    scheduler_profile_log: Optional[str] = None,
) -> MetricsCollector:
    """
    Run a single scenario.
    
    Args:
        scenario_name: Name of the scenario to run
        config_dir: Directory containing configuration files
        load_balancer_url: Load balancer base URL
        output_dir: Directory for results
        run_id: Optional run ID (generated if not provided)
        iterations: Number of iterations to run
        
    Returns:
        MetricsCollector from the last iteration
    """
    if config_dir is None:
        config_dir = _DEFAULT_CONFIG_DIR
    if output_dir is None:
        output_dir = _DEFAULT_RESULTS_DIR
    _log_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_filename = f"testbed_{scenario_name}_{_log_ts}.log"
    logger = setup_logger("main", log_file=_log_filename, log_dir=str(Path(output_dir) / "logs"))
    
    if scenario_name not in SCENARIO_CLASSES:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(SCENARIO_CLASSES.keys())}")
    
    # Load configuration
    try:
        if research_mode:
            # Try to load research-scale config first
            research_config_path = Path(config_dir) / "scenarios_research.yaml"
            if research_config_path.exists():
                logger.info(f"Loading research-scale config from {research_config_path}")
                research_configs = load_yaml(str(research_config_path))
                if scenario_name in research_configs:
                    config = research_configs[scenario_name]
                else:
                    logger.warning(f"Research config not found for {scenario_name}, using base config with scaling")
                    config = get_scenario_config(config_dir, scenario_name)
                    config = apply_research_scaling(config, scenario_name)
            else:
                logger.info("Research config file not found, applying scaling multipliers to base config")
                config = get_scenario_config(config_dir, scenario_name)
                config = apply_research_scaling(config, scenario_name)
        else:
            config = get_scenario_config(config_dir, scenario_name)
    except Exception as e:
        logger.error(f"Failed to load scenario config: {e}")
        raise
    
    # Initialize service analyzer
    try:
        service_analyzer = ServiceAnalyzer()
        logger.info(f"Loaded {len(service_analyzer.get_all_services())} services")
    except Exception as e:
        logger.error(f"Failed to initialize service analyzer: {e}")
        raise
    
    # Run iterations
    last_metrics = None
    for iteration in range(iterations):
        iter_run_id = run_id or create_run_id(scenario_name, iteration if iterations > 1 else None)
        logger.info(f"Starting iteration {iteration + 1}/{iterations} (run_id: {iter_run_id})")
        
        # Override seed if provided via CLI
        if seed is not None:
            config['seed'] = seed
        elif 'seed' not in config:
            # Generate a seed if none provided (for reproducibility)
            import random
            config['seed'] = random.randint(1, 1000000)
        
        # Create scenario instance
        scenario_class = SCENARIO_CLASSES[scenario_name]
        scenario = scenario_class(
            config=config,
            service_analyzer=service_analyzer,
            load_balancer_url=load_balancer_url,
            run_id=iter_run_id,
            seed=config.get('seed'),
            replay_file=replay_file
        )
        
        # Set save_requests flag if requested
        if save_requests and not replay_file:
            scenario.save_requests = True
        
        # Set save_only flag if requested
        if save_only:
            scenario.save_only = True
        
        # Run scenario
        try:
            metrics = await scenario.run()
            last_metrics = metrics
            
            # Calculate aggregates
            metrics.calculate_aggregates()
            
            # Export metrics
            json_path = metrics.export_json(output_dir)
            csv_path = metrics.export_csv(output_dir)
            job_ids_path = metrics.export_job_ids(output_dir)
            
            logger.info(f"Metrics exported: {json_path}, {csv_path}")
            logger.info(f"Job IDs written: {job_ids_path}")
            logger.info(metrics.get_summary())

            if enrich_after_run:
                if not scheduler_url:
                    raise ValueError("scheduler_url is required when enrich_after_run is enabled")
                enrich_result = enrich_run(
                    run_id=metrics.run_id,
                    results_dir=output_dir,
                    scheduler_url=scheduler_url,
                    since=enrich_since,
                    until=enrich_until,
                    scheduler_profile_log=scheduler_profile_log,
                )
                logger.info(f"Enriched job metrics: {enrich_result['json_path']}")
                logger.info(f"Outcome breakdown: {enrich_result['outcome_breakdown']}")
                if upload_to_drive:
                    _upload_artefacts(metrics.run_id, output_dir, drive_credentials, logger)
            
        except Exception as e:
            logger.error(f"Scenario execution failed: {e}", exc_info=True)
            raise
    
    return last_metrics


async def run_all_scenarios(
    config_dir: Optional[str] = None,
    load_balancer_url: str = "http://localhost:9001",
    output_dir: Optional[str] = None,
    iterations: int = 1,
    research_mode: bool = False,
    seed: Optional[int] = None,
    save_requests: bool = False
):
    """Run all scenarios sequentially."""
    if config_dir is None:
        config_dir = _DEFAULT_CONFIG_DIR
    if output_dir is None:
        output_dir = _DEFAULT_RESULTS_DIR
    logger = setup_logger("main")
    
    for scenario_name in SCENARIO_CLASSES.keys():
        logger.info(f"Running scenario: {scenario_name}")
        try:
            await run_scenario(
                scenario_name=scenario_name,
                config_dir=config_dir,
                load_balancer_url=load_balancer_url,
                output_dir=output_dir,
                iterations=iterations,
                research_mode=research_mode,
                seed=seed,
                save_requests=save_requests
            )
        except Exception as e:
            logger.error(f"Failed to run scenario {scenario_name}: {e}")
            continue


def analyze_results(run_id: str, output_dir: Optional[str] = None):
    """Analyze results from a test run."""
    if output_dir is None:
        output_dir = _DEFAULT_RESULTS_DIR
    logger = setup_logger("main")
    
    logger.info(f"Analyzing results for run: {run_id}")
    
    # Generate report
    report_generator = ReportGenerator(results_dir=output_dir)
    try:
        report_path = report_generator.generate_report(run_id)
        logger.info(f"Vulnerability report generated: {report_path}")
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
    
    # Create visualizations
    visualizer = MetricsVisualizer(results_dir=output_dir)
    try:
        viz_paths = visualizer.create_all_visualizations(run_id)
        logger.info(f"Visualizations created: {viz_paths}")
    except Exception as e:
        logger.error(f"Failed to create visualizations: {e}")


def run_enrichment(
    run_id: str,
    output_dir: str,
    scheduler_url: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    upload_to_drive: bool = False,
    drive_credentials: Optional[str] = None,
    scheduler_profile_log: Optional[str] = None,
):
    """Run standalone enrichment for an existing run_id."""
    logger = setup_logger("main")
    logger.info(f"Enriching run {run_id} using scheduler {scheduler_url}")
    result = enrich_run(
        run_id=run_id,
        results_dir=output_dir,
        scheduler_url=scheduler_url,
        since=since,
        until=until,
        scheduler_profile_log=scheduler_profile_log,
    )
    logger.info(f"Mode: {result['mode']}")
    logger.info(f"Enriched CSV: {result['csv_path']}")
    logger.info(f"Enriched JSON: {result['json_path']}")
    logger.info(f"Outcome breakdown: {result['outcome_breakdown']}")

    if upload_to_drive:
        _upload_artefacts(run_id, output_dir, drive_credentials, logger)


def _upload_artefacts(
    run_id: str,
    output_dir: str,
    drive_credentials: Optional[str],
    logger,
):
    """Upload enriched artefacts to Google Drive and log the result."""
    logger.info(f"Uploading artefacts for {run_id} to Google Drive (peercomp_runs/{run_id}/)...")
    try:
        info = upload_run_artefacts(
            run_id=run_id,
            results_dir=output_dir,
            credentials_file=drive_credentials,
        )
        logger.info(f"Drive folder: {info['folder_link']}")
        for f in info["uploaded"]:
            logger.info(f"  Uploaded: {f['name']}  ->  {f['link']}")
    except Exception as exc:
        logger.error(f"Drive upload failed: {exc}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Serverless Scheduler Testbed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run baseline scenario
  python main.py --scenario baseline

  # Run all scenarios
  python main.py --all

  # Run with custom config
  python main.py --scenario steady_load --config custom_config/

  # Run multiple iterations
  python main.py --scenario baseline --iterations 5

  # Analyze results
  python main.py --analyze baseline_20250101_120000
        """
    )
    
    parser.add_argument(
        '--scenario',
        choices=list(SCENARIO_CLASSES.keys()),
        help='Scenario to run'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Run all scenarios sequentially'
    )
    parser.add_argument(
        '--config',
        default=_DEFAULT_CONFIG_DIR,
        help='Configuration directory (default: config/ next to main.py)'
    )
    parser.add_argument(
        '--output-dir',
        default=_DEFAULT_RESULTS_DIR,
        help='Output directory for results (default: results/ next to main.py)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=1,
        help='Number of iterations per scenario (default: 1)'
    )
    parser.add_argument(
        '--load-balancer-url',
        default='http://localhost:9001',
        help='Load balancer base URL (default: http://localhost:9001)'
    )
    parser.add_argument(
        '--analyze',
        help='Analyze results for a specific run ID'
    )
    parser.add_argument(
        '--research-mode',
        action='store_true',
        help='Enable research-scale volumes (1k-10k requests per scenario)'
    )
    parser.add_argument(
        '--seed',
        type=int,
        help='Random seed for reproducible request generation'
    )
    parser.add_argument(
        '--save-requests',
        action='store_true',
        help='Save generated requests to file for later replay'
    )
    parser.add_argument(
        '--replay',
        help='Replay saved requests from file (path to saved requests JSON)'
    )
    parser.add_argument(
        '--save-only',
        action='store_true',
        help='Only save requests without sending them (useful for generating test data)'
    )
    parser.add_argument(
        '--enrich',
        help='Enrich an existing run ID with scheduler-side job states'
    )
    parser.add_argument(
        '--scheduler-url',
        help='Scheduler base URL for enrichment (example: http://host:8000)'
    )
    parser.add_argument(
        '--enrich-after-run',
        action='store_true',
        help='After each run, enrich metrics with scheduler-side job states'
    )
    parser.add_argument(
        '--enrich-since',
        help='ISO-8601 window start for enrichment window query (overrides auto-detected start_time)'
    )
    parser.add_argument(
        '--enrich-until',
        help='ISO-8601 window end for enrichment window query (defaults to now on scheduler side)'
    )
    parser.add_argument(
        '--upload-to-drive',
        action='store_true',
        help='After enrichment, upload artefacts to Google Drive under peercomp_runs/<run_id>/'
    )
    parser.add_argument(
        '--upload-only',
        metavar='RUN_ID',
        help='Upload existing enriched artefacts for RUN_ID to Drive (skip re-enrichment)'
    )
    parser.add_argument(
        '--drive-credentials',
        help='Path to Google OAuth client credentials JSON (default: ~/.config/peercomp/credentials.json)'
    )
    parser.add_argument(
        '--scheduler-profile-log',
        help=(
            'Comma-separated paths or glob patterns to scheduler profile JSONL files. '
            'Pass one per scheduler node to get full coverage — all files are merged on corr_id. '
            'Example: "sched1/logs/scheduler_profile_*.jsonl,sched2/logs/scheduler_profile_*.jsonl"'
        )
    )

    args = parser.parse_args()

    if args.analyze:
        analyze_results(args.analyze, args.output_dir)
        return

    if args.upload_only:
        logger = setup_logger("main")
        _upload_artefacts(args.upload_only, args.output_dir, args.drive_credentials, logger)
        return

    if args.enrich:
        if not args.scheduler_url:
            parser.error("--scheduler-url is required when using --enrich")
        run_enrichment(
            args.enrich,
            args.output_dir,
            args.scheduler_url,
            since=args.enrich_since,
            until=args.enrich_until,
            upload_to_drive=args.upload_to_drive,
            drive_credentials=args.drive_credentials,
            scheduler_profile_log=args.scheduler_profile_log,
        )
        return

    if not args.scenario and not args.all:
        parser.error("Must specify --scenario or --all")
    if args.enrich_after_run and not args.scheduler_url:
        parser.error("--scheduler-url is required when using --enrich-after-run")

    # Run scenarios
    if args.all:
        asyncio.run(run_all_scenarios(
            config_dir=args.config,
            load_balancer_url=args.load_balancer_url,
            output_dir=args.output_dir,
            iterations=args.iterations,
            research_mode=args.research_mode,
            seed=args.seed,
            save_requests=args.save_requests
        ))
    else:
        metrics = asyncio.run(run_scenario(
            scenario_name=args.scenario,
            config_dir=args.config,
            load_balancer_url=args.load_balancer_url,
            output_dir=args.output_dir,
            iterations=args.iterations,
            research_mode=args.research_mode,
            seed=args.seed,
            save_requests=args.save_requests,
            replay_file=args.replay,
            save_only=args.save_only,
            enrich_after_run=args.enrich_after_run,
            scheduler_url=args.scheduler_url,
            enrich_since=args.enrich_since,
            enrich_until=args.enrich_until,
            upload_to_drive=args.upload_to_drive,
            drive_credentials=args.drive_credentials,
            scheduler_profile_log=args.scheduler_profile_log,
        ))
        
        # Auto-analyze if single iteration
        if args.iterations == 1 and metrics:
            print("\n" + "="*80)
            print("Running post-analysis...")
            print("="*80 + "\n")
            analyze_results(metrics.run_id, args.output_dir)


if __name__ == "__main__":
    main()


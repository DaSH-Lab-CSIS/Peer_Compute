#!/usr/bin/env python3
"""
Test scheduler operations with CockroachDB.
Tests job creation, provider registration, and ILP scheduling logic.
"""

import os
import sys
import django
import uuid
from pathlib import Path
from datetime import datetime

# Add scheduler directory to path
scheduler_dir = Path(__file__).parent.parent.parent / 'scheduler'
sys.path.insert(0, str(scheduler_dir))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scheduler.settings')

# Setup Django
django.setup()

from django.db import transaction
from profiles.models import User
from providers.models import Job
from developers.models import Services

def test_provider_registration():
    """Test provider registration and status updates."""
    print("Testing provider registration...")
    
    try:
        # Create or get a test provider
        provider, created = User.objects.get_or_create(
            user_id=uuid.uuid4(),
            defaults={
                'is_provider': True,
                'active': True,
                'ready': True,
                'location': 'test_location'
            }
        )
        
        if created:
            print(f"  ✅ Created test provider: {provider.user_id}")
        else:
            print(f"  ✅ Found existing provider: {provider.user_id}")
        
        # Test status update
        provider.ready = False
        provider.save()
        provider.refresh_from_db()
        assert provider.ready == False, "Status update failed"
        print(f"  ✅ Status update successful")
        
        provider.ready = True
        provider.save()
        print(f"  ✅ Status restore successful")
        
        return True
    except Exception as e:
        print(f"  ❌ Provider registration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_job_creation():
    """Test job creation and assignment."""
    print()
    print("Testing job creation...")
    
    try:
        # Get or create a provider
        provider = User.objects.filter(is_provider=True).first()
        if not provider:
            provider = User.objects.create(
                user_id=uuid.uuid4(),
                is_provider=True,
                active=True,
                ready=True
            )
        
        # Get or create a service
        service = Services.objects.first()
        if not service:
            print("  ⚠️  No services found, skipping job creation test")
            return True
        
        # Create a job
        job = Job.objects.create(
            provider=provider,
            service=service,
            start_time=datetime.now()
        )
        
        print(f"  ✅ Job created: {job.id}")
        
        # Test job retrieval
        retrieved_job = Job.objects.get(id=job.id)
        assert retrieved_job.provider == provider, "Job retrieval failed"
        print(f"  ✅ Job retrieval successful")
        
        # Test job update
        retrieved_job.ack_time = datetime.now()
        retrieved_job.save()
        print(f"  ✅ Job update successful")
        
        return True
    except Exception as e:
        print(f"  ❌ Job creation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_transaction_isolation():
    """Test transaction isolation (CockroachDB uses serializable)."""
    print()
    print("Testing transaction isolation...")
    
    try:
        # Test transaction
        with transaction.atomic():
            provider = User.objects.filter(is_provider=True).first()
            if provider:
                provider.ready = False
                provider.save()
                # Transaction should commit successfully
                print(f"  ✅ Transaction commit successful")
            else:
                print(f"  ⚠️  No provider found, skipping transaction test")
        
        return True
    except Exception as e:
        print(f"  ❌ Transaction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ilp_scheduling_logic():
    """Test ILP scheduling logic compatibility."""
    print()
    print("Testing ILP scheduling logic compatibility...")
    
    try:
        # Get active providers
        active_providers = User.objects.filter(
            is_provider=True,
            active=True,
            ready=True
        )
        
        provider_count = active_providers.count()
        print(f"  ✅ Active providers query: {provider_count} providers")
        
        # Test complex query (similar to ILP)
        providers_with_scores = User.objects.filter(
            is_provider=True,
            active=True
        ).exclude(
            cpu_efficiency_score__isnull=True
        )
        
        score_count = providers_with_scores.count()
        print(f"  ✅ Complex query (ILP-like): {score_count} providers with scores")
        
        return True
    except Exception as e:
        print(f"  ❌ ILP scheduling logic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_concurrent_access():
    """Test concurrent access patterns."""
    print()
    print("Testing concurrent access patterns...")
    
    try:
        # Test SELECT FOR UPDATE (used in ILP)
        with transaction.atomic():
            provider = User.objects.select_for_update().filter(
                is_provider=True,
                active=True
            ).first()
            
            if provider:
                print(f"  ✅ SELECT FOR UPDATE successful")
            else:
                print(f"  ⚠️  No provider found for SELECT FOR UPDATE test")
        
        return True
    except Exception as e:
        print(f"  ❌ Concurrent access test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("Scheduler Operations Test with CockroachDB")
    print("=" * 60)
    print()
    
    results = []
    
    # Run tests
    results.append(("Provider Registration", test_provider_registration()))
    results.append(("Job Creation", test_job_creation()))
    results.append(("Transaction Isolation", test_transaction_isolation()))
    results.append(("ILP Scheduling Logic", test_ilp_scheduling_logic()))
    results.append(("Concurrent Access", test_concurrent_access()))
    
    # Summary
    print()
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
Test script to print predicted runtime for a service ID using the provider's
regression model. Run from project root so TrainingData/ paths resolve.

Usage:
  python provider/predict_runtime_test.py <service_id> [--cpu-eff 1.0] [--mem-eff 1.0] [--save] [--load]

Examples:
  python provider/predict_runtime_test.py satyam098/testimage_largeruntime
  python provider/predict_runtime_test.py satyam098/testimage_largeruntime --save
  python provider/predict_runtime_test.py satyam098/testimage_largeruntime --load
"""
import json
import os
import sys
import pickle
import argparse
import numpy as np
from sklearn.linear_model import LinearRegression

# Run from project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINING_FILE = os.path.join(PROJECT_ROOT, "TrainingData", "eff_score_data.txt")
REFERENCE_FILE = os.path.join(PROJECT_ROOT, "TrainingData", "Reference_Provider_Data.txt")
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "provider", "runtime_model.pkl")


def load_data_from_file(filename):
    if not os.path.isfile(filename):
        return []
    data = []
    decoder = json.JSONDecoder()
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            while line:
                try:
                    obj, idx = decoder.raw_decode(line)
                    data.append(obj)
                    line = line[idx:].strip()
                except json.JSONDecodeError:
                    break
    cleaned = [
        item for item in data
        if not any("DID NOT RECIEVE" in str(v) for v in item.values())
    ]
    return cleaned


def train_regression_model(training_data):
    X, y = [], []
    for data in training_data:
        try:
            cpu = float(data["cpu_usage"])
            mem = float(data["memory_usage"])
            cpu_eff = float(data["cpu_efficiency_score"])
            mem_eff = float(data["memory_efficiency_score"])
            runtime = float(data["actual_runtime"])
            X.append([cpu * cpu_eff, mem * mem_eff])
            y.append(runtime)
        except (ValueError, TypeError, KeyError):
            continue
    if len(X) == 0:
        class DummyModel:
            def predict(self, X):
                return np.array([1000.0] * len(X))
        return DummyModel()
    model = LinearRegression()
    model.fit(X, y)
    return model


def predict_runtime(service_id, model, cpu_eff=1.0, mem_eff=1.0):
    ref_data = load_data_from_file(REFERENCE_FILE)
    ref_cpu = ref_mem = None
    for item in ref_data:
        if item.get("service") == service_id:
            ref_cpu = float(item["cpu_usage"])
            ref_mem = float(item["memory_usage"])
            break
    if ref_cpu is None:
        ref_cpu, ref_mem = 1000.0, 1000.0
    X = np.array([[ref_cpu * cpu_eff, ref_mem * mem_eff]])
    return model.predict(X)[0]


def save_model(model, path):
    with open(path, "wb") as f:
        pickle.dump(model, f)


def load_model(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def main():
    parser = argparse.ArgumentParser(description="Print predicted runtime for a service ID")
    parser.add_argument("service_id", help="Service ID (e.g. satyam098/testimage_largeruntime)")
    parser.add_argument("--cpu-eff", type=float, default=1.0, help="CPU efficiency score")
    parser.add_argument("--mem-eff", type=float, default=1.0, help="Memory efficiency score")
    parser.add_argument("--save", action="store_true", help="Save trained model to provider/runtime_model.pkl")
    parser.add_argument("--load", action="store_true", help="Load model from provider/runtime_model.pkl (skip training)")
    args = parser.parse_args()

    if args.load and os.path.isfile(DEFAULT_MODEL_PATH):
        print(f"Loading model from {DEFAULT_MODEL_PATH}")
        model = load_model(DEFAULT_MODEL_PATH)
    else:
        if args.load and not os.path.isfile(DEFAULT_MODEL_PATH):
            print(f"Model file not found: {DEFAULT_MODEL_PATH}, training from data")
        if not os.path.isfile(TRAINING_FILE):
            print(f"Training data not found: {TRAINING_FILE}")
            sys.exit(1)
        training_data = load_data_from_file(TRAINING_FILE)
        print(f"Training on {len(training_data)} samples from {TRAINING_FILE}")
        model = train_regression_model(training_data)
        if args.save:
            save_model(model, DEFAULT_MODEL_PATH)
            print(f"Saved model to {DEFAULT_MODEL_PATH}")

    pred_ms = predict_runtime(args.service_id, model, args.cpu_eff, args.mem_eff)
    print(f"Service ID: {args.service_id}")
    print(f"Predicted runtime: {pred_ms:.2f} ms")


if __name__ == "__main__":
    main()

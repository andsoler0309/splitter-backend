#!/usr/bin/env python3
"""
Simple memory monitoring script for debugging memory usage in production
"""
import psutil
import os
import time

def get_memory_usage():
    """Get current memory usage in MB"""
    try:
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        return memory_mb
    except Exception:
        return 0

def log_memory_usage(context=""):
    """Log current memory usage"""
    memory_mb = get_memory_usage()
    print(f"[MEMORY] {context}: {memory_mb:.1f} MB")
    return memory_mb

def check_memory_limit(limit_mb=450):
    """Check if approaching memory limit and warn"""
    memory_mb = get_memory_usage()
    if memory_mb > limit_mb:
        print(f"[WARNING] High memory usage: {memory_mb:.1f} MB (limit: {limit_mb} MB)")
        return True
    return False

if __name__ == "__main__":
    # Monitor memory usage for testing
    while True:
        log_memory_usage("Monitor")
        time.sleep(5)

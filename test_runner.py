#!/usr/bin/env python3
"""
Main test runner script for the entire didimdol-voice-agent project.
Runs both backend unit tests and integration tests.
"""

import sys
import subprocess
import argparse
import concurrent.futures
from pathlib import Path


def run_command(cmd, description, cwd=None):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Working Directory: {cwd or Path.cwd()}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"❌ {description} failed with exit code {result.returncode}")
        return False
    else:
        print(f"✅ {description} completed successfully")
        return True


def run_backend_tests(test_type, parallel=False, verbose=False):
    """Run backend tests."""
    backend_path = Path(__file__).parent / "backend"
    
    pytest_cmd = ["python", "-m", "pytest"]
    if verbose:
        pytest_cmd.append("-v")
    if parallel:
        pytest_cmd.extend(["-n", "auto"])
    
    if test_type == "unit":
        cmd = pytest_cmd + ["tests/", "-m", "unit"]
        return run_command(cmd, "Backend Unit Tests", cwd=backend_path)
    elif test_type == "all":
        cmd = pytest_cmd + ["tests/"]
        return run_command(cmd, "All Backend Tests", cwd=backend_path)
    elif test_type == "quick":
        cmd = pytest_cmd + ["tests/", "-m", "not slow"]
        return run_command(cmd, "Backend Quick Tests", cwd=backend_path)
    
    return True


def run_integration_tests(test_type, parallel=False, verbose=False):
    """Run integration tests."""
    root_path = Path(__file__).parent
    
    pytest_cmd = ["python", "-m", "pytest"]
    if verbose:
        pytest_cmd.append("-v")
    if parallel:
        pytest_cmd.extend(["-n", "auto"])
    
    if test_type == "integration":
        cmd = pytest_cmd + ["tests/", "-m", "integration"]
        return run_command(cmd, "Integration Tests", cwd=root_path)
    elif test_type == "e2e":
        cmd = pytest_cmd + ["tests/", "-m", "e2e"]
        return run_command(cmd, "End-to-End Tests", cwd=root_path)
    elif test_type == "api":
        cmd = pytest_cmd + ["tests/", "-m", "api"]
        return run_command(cmd, "API Tests", cwd=root_path)
    elif test_type == "all":
        cmd = pytest_cmd + ["tests/"]
        return run_command(cmd, "All Integration Tests", cwd=root_path)
    
    return True


def run_coverage_tests():
    """Run comprehensive coverage tests."""
    root_path = Path(__file__).parent
    
    # Backend coverage
    backend_cmd = [
        "python", "-m", "pytest",
        "backend/tests/",
        "--cov=backend/app",
        "--cov-report=term-missing",
        "--cov-report=html:backend/htmlcov",
        "--cov-fail-under=80"
    ]
    
    backend_success = run_command(backend_cmd, "Backend Coverage", cwd=root_path)
    
    # Integration coverage
    integration_cmd = [
        "python", "-m", "pytest", 
        "tests/",
        "--cov=backend/app",
        "--cov-append",
        "--cov-report=term-missing",
        "--cov-report=html:htmlcov",
        "--cov-fail-under=70"
    ]
    
    integration_success = run_command(integration_cmd, "Integration Coverage", cwd=root_path)
    
    return backend_success and integration_success


def run_lint_checks():
    """Run code quality checks."""
    root_path = Path(__file__).parent
    backend_path = root_path / "backend"
    
    commands = [
        (["python", "-m", "black", "--check", "backend/app/"], "Backend Black Format Check", root_path),
        (["python", "-m", "isort", "--check-only", "backend/app/"], "Backend Import Sort Check", root_path),
        (["python", "-m", "flake8", "backend/app/"], "Backend Flake8 Linting", root_path),
        (["python", "-m", "mypy", "app/"], "Backend Type Checking", backend_path),
    ]
    
    success = True
    for cmd, description, cwd in commands:
        if not run_command(cmd, description, cwd):
            success = False
    
    return success


def run_performance_tests():
    """Run performance and load tests."""
    root_path = Path(__file__).parent
    
    cmd = [
        "python", "-m", "pytest",
        "tests/",
        "-m", "performance",
        "--benchmark-only",
        "--benchmark-json=benchmark_results.json"
    ]
    
    return run_command(cmd, "Performance Tests", cwd=root_path)


def main():
    parser = argparse.ArgumentParser(description="Didimdol Voice Agent Test Runner")
    parser.add_argument(
        "test_type",
        choices=[
            "unit", "integration", "e2e", "api", "all", 
            "backend", "quick", "coverage", "lint", "performance"
        ],
        help="Type of tests to run"
    )
    parser.add_argument(
        "--parallel", "-p",
        action="store_true",
        help="Run tests in parallel"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--failfast", "-x",
        action="store_true",
        help="Stop on first failure"
    )
    parser.add_argument(
        "--concurrent",
        action="store_true",
        help="Run backend and integration tests concurrently"
    )
    
    args = parser.parse_args()
    
    success = True
    
    if args.test_type == "unit":
        success = run_backend_tests("unit", args.parallel, args.verbose)
        
    elif args.test_type == "integration":
        success = run_integration_tests("integration", args.parallel, args.verbose)
        
    elif args.test_type == "e2e":
        success = run_integration_tests("e2e", args.parallel, args.verbose)
        
    elif args.test_type == "api":
        success = run_integration_tests("api", args.parallel, args.verbose)
        
    elif args.test_type == "backend":
        success = run_backend_tests("all", args.parallel, args.verbose)
        
    elif args.test_type == "quick":
        # Run quick tests for both backend and integration
        if args.concurrent:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                backend_future = executor.submit(run_backend_tests, "quick", args.parallel, args.verbose)
                integration_future = executor.submit(run_integration_tests, "integration", args.parallel, args.verbose)
                
                backend_success = backend_future.result()
                integration_success = integration_future.result()
                success = backend_success and integration_success
        else:
            success = run_backend_tests("quick", args.parallel, args.verbose)
            if success:
                success = run_integration_tests("integration", args.parallel, args.verbose)
        
    elif args.test_type == "coverage":
        success = run_coverage_tests()
        
    elif args.test_type == "lint":
        success = run_lint_checks()
        
    elif args.test_type == "performance":
        success = run_performance_tests()
        
    elif args.test_type == "all":
        # Run comprehensive test suite
        test_stages = [
            ("Backend Unit Tests", lambda: run_backend_tests("all", args.parallel, args.verbose)),
            ("Integration Tests", lambda: run_integration_tests("all", args.parallel, args.verbose)),
            ("Code Quality Checks", run_lint_checks),
        ]
        
        for stage_name, stage_func in test_stages:
            print(f"\n🚀 Starting: {stage_name}")
            if not stage_func():
                success = False
                print(f"❌ {stage_name} failed")
            else:
                print(f"✅ {stage_name} passed")
    
    # Final results
    print(f"\n{'='*60}")
    if success:
        print(f"🎉 All tests completed successfully!")
        print(f"{'='*60}")
        sys.exit(0)
    else:
        print(f"💥 Some tests failed!")
        print(f"{'='*60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Test runner script for backend module.
Provides convenient commands for running different types of tests.
"""

import sys
import subprocess
import argparse
import os
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    # Set up environment with virtual environment and PYTHONPATH
    backend_dir = Path(__file__).parent
    env = {
        **os.environ,
        'PYTHONPATH': str(backend_dir),
    }
    
    # Activate virtual environment if it exists
    venv_python = backend_dir / 'venv' / 'bin' / 'python'
    if venv_python.exists():
        # Replace 'python' with the virtual environment python
        if cmd[0] == 'python':
            cmd[0] = str(venv_python)
    
    result = subprocess.run(cmd, cwd=backend_dir, env=env)
    if result.returncode != 0:
        print(f"❌ {description} failed with exit code {result.returncode}")
        return False
    else:
        print(f"✅ {description} completed successfully")
        return True


def main():
    parser = argparse.ArgumentParser(description="Backend test runner")
    parser.add_argument(
        "test_type",
        choices=["unit", "integration", "all", "quick", "coverage", "lint"],
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
    
    args = parser.parse_args()
    
    # Base pytest command
    pytest_cmd = ["python", "-m", "pytest"]
    
    # Add common options
    if args.verbose:
        pytest_cmd.append("-v")
    if args.failfast:
        pytest_cmd.append("-x")
    if args.parallel:
        pytest_cmd.extend(["-n", "auto"])
    
    success = True
    
    if args.test_type == "unit":
        cmd = pytest_cmd + ["tests/", "-m", "unit"]
        success = run_command(cmd, "Unit Tests")
        
    elif args.test_type == "integration":
        cmd = pytest_cmd + ["tests/", "-m", "integration"]
        success = run_command(cmd, "Integration Tests")
        
    elif args.test_type == "quick":
        cmd = pytest_cmd + ["tests/", "-m", "not slow"]
        success = run_command(cmd, "Quick Tests")
        
    elif args.test_type == "coverage":
        cmd = pytest_cmd + [
            "tests/",
            "--cov=app",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
            "--cov-fail-under=80"
        ]
        success = run_command(cmd, "Coverage Tests")
        
    elif args.test_type == "lint":
        commands = [
            (["python", "-m", "black", "--check", "app/", "tests/"], "Black Format Check"),
            (["python", "-m", "isort", "--check-only", "app/", "tests/"], "Import Sort Check"),
            (["python", "-m", "flake8", "app/", "tests/"], "Flake8 Linting"),
            (["python", "-m", "mypy", "app/"], "Type Checking"),
        ]
        
        for cmd, description in commands:
            if not run_command(cmd, description):
                success = False
                
    elif args.test_type == "all":
        commands = [
            (pytest_cmd + ["tests/", "-m", "unit"], "Unit Tests"),
            (pytest_cmd + ["tests/", "-m", "integration"], "Integration Tests"),
        ]
        
        for cmd, description in commands:
            if not run_command(cmd, description):
                success = False
    
    if success:
        print(f"\n🎉 All tests completed successfully!")
        sys.exit(0)
    else:
        print(f"\n💥 Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
"""
Comprehensive test runner for 디딤돌 voice consultation agent.

This script runs all test scenarios including realistic conversations, edge cases,
and answer validation, providing detailed reporting and analysis.
"""

import asyncio
import pytest
import sys
import time
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse

# Import test modules
from test_realistic_scenarios import (
    TestRealisticDidimdolScenarios,
    TestRealisticJeonseScenarios, 
    TestRealisticAccountScenarios,
    TestRealisticEdgeCases,
    TestConversationContextManagement
)
from test_edge_cases import (
    TestServiceFailureScenarios,
    TestInputVariationScenarios,
    TestConcurrencyAndPerformanceScenarios,
    TestStateManagementEdgeCases,
    TestSecurityAndInputValidation,
    TestResourceLimitScenarios,
    TestDataValidationScenarios
)
from test_answer_validation import (
    TestAnswerValidationSystem,
    TestIntegratedValidationScenarios,
    AnswerValidator,
    ValidationResult
)


@dataclass
class TestResult:
    """Individual test result."""
    test_name: str
    status: str  # PASSED, FAILED, SKIPPED, ERROR
    duration: float
    error_message: Optional[str] = None
    validation_score: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class TestSuiteResult:
    """Test suite result summary."""
    suite_name: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    average_validation_score: Optional[float] = None
    test_results: List[TestResult] = None


@dataclass
class ComprehensiveTestReport:
    """Comprehensive test report."""
    total_tests: int
    total_passed: int
    total_failed: int
    total_skipped: int
    total_errors: int
    total_duration: float
    overall_score: float
    suite_results: List[TestSuiteResult]
    validation_summary: Dict[str, Any]
    recommendations: List[str]


class ComprehensiveTestRunner:
    """Comprehensive test runner with detailed reporting."""
    
    def __init__(self, verbose: bool = False, save_report: bool = True):
        self.verbose = verbose
        self.save_report = save_report
        self.validator = AnswerValidator()
        self.test_results = []
        self.suite_results = []
    
    async def run_all_tests(self) -> ComprehensiveTestReport:
        """Run all test suites and generate comprehensive report."""
        print("🧪 Starting Comprehensive Test Suite for 디딤돌 Voice Consultation Agent")
        print("=" * 80)
        
        start_time = time.time()
        
        # Define test suites
        test_suites = [
            ("Realistic Korean Conversations", [
                TestRealisticDidimdolScenarios,
                TestRealisticJeonseScenarios,
                TestRealisticAccountScenarios,
                TestRealisticEdgeCases,
                TestConversationContextManagement
            ]),
            ("Edge Cases and Error Handling", [
                TestServiceFailureScenarios,
                TestInputVariationScenarios,
                TestConcurrencyAndPerformanceScenarios,
                TestStateManagementEdgeCases,
                TestSecurityAndInputValidation,
                TestResourceLimitScenarios,
                TestDataValidationScenarios
            ]),
            ("Answer Validation", [
                TestAnswerValidationSystem,
                TestIntegratedValidationScenarios
            ])
        ]
        
        # Run each test suite
        for suite_name, test_classes in test_suites:
            print(f"\n📋 Running Test Suite: {suite_name}")
            print("-" * 50)
            
            suite_result = await self._run_test_suite(suite_name, test_classes)
            self.suite_results.append(suite_result)
            
            self._print_suite_summary(suite_result)
        
        # Generate comprehensive report
        total_duration = time.time() - start_time
        report = self._generate_comprehensive_report(total_duration)
        
        # Print and save report
        self._print_comprehensive_report(report)
        
        if self.save_report:
            self._save_report(report)
        
        return report
    
    async def _run_test_suite(self, suite_name: str, test_classes: List) -> TestSuiteResult:
        """Run a specific test suite."""
        suite_start_time = time.time()
        suite_results = []
        
        for test_class in test_classes:
            class_name = test_class.__name__
            if self.verbose:
                print(f"  🔍 Running {class_name}")
            
            # Get test methods
            test_methods = [
                method for method in dir(test_class) 
                if method.startswith('test_') and callable(getattr(test_class, method))
            ]
            
            # Run each test method
            for method_name in test_methods:
                test_start_time = time.time()
                test_name = f"{class_name}.{method_name}"
                
                try:
                    # Create test instance and run test
                    test_instance = test_class()
                    test_method = getattr(test_instance, method_name)
                    
                    # Handle async tests
                    if asyncio.iscoroutinefunction(test_method):
                        await test_method()
                    else:
                        test_method()
                    
                    test_duration = time.time() - test_start_time
                    
                    # Create test result
                    result = TestResult(
                        test_name=test_name,
                        status="PASSED",
                        duration=test_duration
                    )
                    
                    if self.verbose:
                        print(f"    ✅ {method_name} ({test_duration:.2f}s)")
                
                except pytest.skip.Exception as e:
                    test_duration = time.time() - test_start_time
                    result = TestResult(
                        test_name=test_name,
                        status="SKIPPED",
                        duration=test_duration,
                        error_message=str(e)
                    )
                    
                    if self.verbose:
                        print(f"    ⏭️  {method_name} (SKIPPED: {str(e)})")
                
                except AssertionError as e:
                    test_duration = time.time() - test_start_time
                    result = TestResult(
                        test_name=test_name,
                        status="FAILED",
                        duration=test_duration,
                        error_message=str(e)
                    )
                    
                    if self.verbose:
                        print(f"    ❌ {method_name} (FAILED: {str(e)})")
                
                except Exception as e:
                    test_duration = time.time() - test_start_time
                    result = TestResult(
                        test_name=test_name,
                        status="ERROR",
                        duration=test_duration,
                        error_message=str(e)
                    )
                    
                    if self.verbose:
                        print(f"    💥 {method_name} (ERROR: {str(e)})")
                
                suite_results.append(result)
                self.test_results.append(result)
        
        # Calculate suite statistics
        suite_duration = time.time() - suite_start_time
        total_tests = len(suite_results)
        passed = len([r for r in suite_results if r.status == "PASSED"])
        failed = len([r for r in suite_results if r.status == "FAILED"])
        skipped = len([r for r in suite_results if r.status == "SKIPPED"])
        errors = len([r for r in suite_results if r.status == "ERROR"])
        
        # Calculate average validation score if applicable
        validation_scores = [r.validation_score for r in suite_results if r.validation_score is not None]
        avg_validation_score = sum(validation_scores) / len(validation_scores) if validation_scores else None
        
        return TestSuiteResult(
            suite_name=suite_name,
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration=suite_duration,
            average_validation_score=avg_validation_score,
            test_results=suite_results
        )
    
    def _print_suite_summary(self, suite_result: TestSuiteResult):
        """Print summary for a test suite."""
        print(f"📊 {suite_result.suite_name} Results:")
        print(f"   Total: {suite_result.total_tests}")
        print(f"   ✅ Passed: {suite_result.passed}")
        print(f"   ❌ Failed: {suite_result.failed}")
        print(f"   ⏭️  Skipped: {suite_result.skipped}")
        print(f"   💥 Errors: {suite_result.errors}")
        print(f"   ⏱️  Duration: {suite_result.duration:.2f}s")
        
        if suite_result.average_validation_score is not None:
            print(f"   🎯 Avg Validation Score: {suite_result.average_validation_score:.2f}")
        
        success_rate = (suite_result.passed / suite_result.total_tests * 100) if suite_result.total_tests > 0 else 0
        print(f"   📈 Success Rate: {success_rate:.1f}%")
    
    def _generate_comprehensive_report(self, total_duration: float) -> ComprehensiveTestReport:
        """Generate comprehensive test report."""
        # Calculate totals
        total_tests = len(self.test_results)
        total_passed = len([r for r in self.test_results if r.status == "PASSED"])
        total_failed = len([r for r in self.test_results if r.status == "FAILED"])
        total_skipped = len([r for r in self.test_results if r.status == "SKIPPED"])
        total_errors = len([r for r in self.test_results if r.status == "ERROR"])
        
        # Calculate overall score
        success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        overall_score = success_rate / 100
        
        # Generate validation summary
        validation_summary = self._generate_validation_summary()
        
        # Generate recommendations
        recommendations = self._generate_recommendations()
        
        return ComprehensiveTestReport(
            total_tests=total_tests,
            total_passed=total_passed,
            total_failed=total_failed,
            total_skipped=total_skipped,
            total_errors=total_errors,
            total_duration=total_duration,
            overall_score=overall_score,
            suite_results=self.suite_results,
            validation_summary=validation_summary,
            recommendations=recommendations
        )
    
    def _generate_validation_summary(self) -> Dict[str, Any]:
        """Generate validation summary."""
        validation_scores = [r.validation_score for r in self.test_results if r.validation_score is not None]
        
        if not validation_scores:
            return {"message": "No validation scores available"}
        
        return {
            "total_validated_tests": len(validation_scores),
            "average_score": sum(validation_scores) / len(validation_scores),
            "min_score": min(validation_scores),
            "max_score": max(validation_scores),
            "high_quality_responses": len([s for s in validation_scores if s >= 0.8]),
            "medium_quality_responses": len([s for s in validation_scores if 0.6 <= s < 0.8]),
            "low_quality_responses": len([s for s in validation_scores if s < 0.6])
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on test results."""
        recommendations = []
        
        # Analyze failure patterns
        failed_tests = [r for r in self.test_results if r.status == "FAILED"]
        error_tests = [r for r in self.test_results if r.status == "ERROR"]
        
        if failed_tests:
            recommendations.append(
                f"🔧 Address {len(failed_tests)} failing tests to improve system reliability"
            )
        
        if error_tests:
            recommendations.append(
                f"🚨 Fix {len(error_tests)} tests with errors - these indicate system issues"
            )
        
        # Analyze validation scores
        validation_summary = self._generate_validation_summary()
        if "average_score" in validation_summary:
            avg_score = validation_summary["average_score"]
            if avg_score < 0.7:
                recommendations.append(
                    f"📈 Improve response quality - current average validation score is {avg_score:.2f}"
                )
            
            if validation_summary["low_quality_responses"] > 0:
                recommendations.append(
                    f"⚠️  Address {validation_summary['low_quality_responses']} low-quality responses"
                )
        
        # Performance recommendations
        slow_tests = [r for r in self.test_results if r.duration > 5.0]
        if slow_tests:
            recommendations.append(
                f"⚡ Optimize performance for {len(slow_tests)} slow tests"
            )
        
        # Success recommendations
        success_rate = (len([r for r in self.test_results if r.status == "PASSED"]) / len(self.test_results) * 100) if self.test_results else 0
        if success_rate >= 90:
            recommendations.append("🎉 Excellent test coverage and system stability!")
        elif success_rate >= 80:
            recommendations.append("👍 Good system stability with room for improvement")
        else:
            recommendations.append("🔴 System needs significant improvements to ensure reliability")
        
        return recommendations
    
    def _print_comprehensive_report(self, report: ComprehensiveTestReport):
        """Print comprehensive test report."""
        print("\n" + "=" * 80)
        print("📋 COMPREHENSIVE TEST REPORT")
        print("=" * 80)
        
        print(f"\n📊 Overall Results:")
        print(f"   Total Tests: {report.total_tests}")
        print(f"   ✅ Passed: {report.total_passed}")
        print(f"   ❌ Failed: {report.total_failed}")
        print(f"   ⏭️  Skipped: {report.total_skipped}")
        print(f"   💥 Errors: {report.total_errors}")
        print(f"   ⏱️  Total Duration: {report.total_duration:.2f}s")
        print(f"   🎯 Overall Score: {report.overall_score:.2%}")
        
        # Validation summary
        if "average_score" in report.validation_summary:
            print(f"\n🔍 Validation Summary:")
            vs = report.validation_summary
            print(f"   Validated Tests: {vs['total_validated_tests']}")
            print(f"   Average Score: {vs['average_score']:.2f}")
            print(f"   Score Range: {vs['min_score']:.2f} - {vs['max_score']:.2f}")
            print(f"   High Quality (≥0.8): {vs['high_quality_responses']}")
            print(f"   Medium Quality (0.6-0.8): {vs['medium_quality_responses']}")
            print(f"   Low Quality (<0.6): {vs['low_quality_responses']}")
        
        # Recommendations
        if report.recommendations:
            print(f"\n💡 Recommendations:")
            for i, rec in enumerate(report.recommendations, 1):
                print(f"   {i}. {rec}")
        
        # Detailed suite results
        print(f"\n📋 Suite Details:")
        for suite in report.suite_results:
            print(f"\n   {suite.suite_name}:")
            print(f"     Tests: {suite.total_tests} | Passed: {suite.passed} | Failed: {suite.failed}")
            print(f"     Duration: {suite.duration:.2f}s | Success Rate: {(suite.passed/suite.total_tests*100):.1f}%")
        
        print("\n" + "=" * 80)
    
    def _save_report(self, report: ComprehensiveTestReport):
        """Save report to file."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"test_report_{timestamp}.json"
        filepath = Path(__file__).parent / "reports" / filename
        
        # Create reports directory if it doesn't exist
        filepath.parent.mkdir(exist_ok=True)
        
        # Convert report to dict for JSON serialization
        report_dict = asdict(report)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Report saved to: {filepath}")


async def main():
    """Main function to run comprehensive tests."""
    parser = argparse.ArgumentParser(description="Comprehensive test runner for 디딤돌 voice agent")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-save", action="store_true", help="Don't save report to file")
    parser.add_argument("--quick", action="store_true", help="Run quick test subset only")
    
    args = parser.parse_args()
    
    runner = ComprehensiveTestRunner(
        verbose=args.verbose,
        save_report=not args.no_save
    )
    
    try:
        report = await runner.run_all_tests()
        
        # Exit with appropriate code
        if report.total_failed > 0 or report.total_errors > 0:
            print(f"\n❌ Tests failed. Exit code: 1")
            sys.exit(1)
        else:
            print(f"\n✅ All tests passed. Exit code: 0")
            sys.exit(0)
            
    except KeyboardInterrupt:
        print("\n⏹️  Test run interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n💥 Test runner error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
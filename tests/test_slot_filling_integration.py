#!/usr/bin/env python3
"""
Slot Filling 시스템 통합 테스트

전체 플로우부터 엣지 케이스까지 포괄적인 테스트
"""

import pytest
import asyncio
import json
from typing import Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from backend.app.api.V1.chat import send_slot_filling_update, should_send_slot_filling_update, INFO_COLLECTION_STAGES
from backend.app.graph.state import AgentState


class TestSlotFillingIntegration:
    """Slot Filling 통합 테스트"""
    
    @pytest.fixture
    def mock_websocket(self):
        """WebSocket 모킹"""
        websocket = AsyncMock()
        websocket.send_json = AsyncMock()
        return websocket
    
    @pytest.fixture
    def sample_scenario_data(self):
        """샘플 시나리오 데이터"""
        return {
            "required_info_fields": [
                {
                    "key": "loan_purpose_confirmed",
                    "display_name": "대출 목적",
                    "type": "boolean",
                    "required": True,
                    "description": "주택 구입 목적인지 확인"
                },
                {
                    "key": "marital_status",
                    "display_name": "결혼 상태",
                    "type": "choice",
                    "choices": ["미혼", "기혼", "예비부부"],
                    "required": True,
                    "description": "고객의 결혼 상태"
                },
                {
                    "key": "annual_income",
                    "display_name": "연소득",
                    "type": "number",
                    "unit": "만원",
                    "required": True,
                    "description": "연간 소득 금액"
                },
                {
                    "key": "spouse_income",
                    "display_name": "배우자 소득",
                    "type": "number",
                    "unit": "만원",
                    "required": False,
                    "depends_on": {
                        "field": "marital_status",
                        "value": "기혼"
                    }
                }
            ],
            "field_groups": [
                {
                    "id": "personal_info",
                    "name": "개인 정보",
                    "fields": ["loan_purpose_confirmed", "marital_status"]
                },
                {
                    "id": "financial_info",
                    "name": "재무 정보",
                    "fields": ["annual_income", "spouse_income"]
                }
            ]
        }
    
    @pytest.fixture
    def sample_agent_state(self, sample_scenario_data):
        """샘플 에이전트 상태"""
        return {
            "current_product_type": "didimdol",
            "active_scenario_data": sample_scenario_data,
            "collected_product_info": {
                "loan_purpose_confirmed": True,
                "marital_status": "기혼"
            },
            "current_scenario_stage_id": "ask_missing_info_group2"
        }

    @pytest.mark.asyncio
    async def test_basic_slot_filling_update(self, mock_websocket, sample_agent_state):
        """기본 slot filling 업데이트 테스트"""
        
        await send_slot_filling_update(mock_websocket, sample_agent_state)
        
        # WebSocket으로 메시지가 전송되었는지 확인
        mock_websocket.send_json.assert_called_once()
        
        # 전송된 메시지 내용 검증
        sent_message = mock_websocket.send_json.call_args[0][0]
        
        assert sent_message["type"] == "slot_filling_update"
        assert sent_message["productType"] == "didimdol"
        assert len(sent_message["requiredFields"]) == 4
        assert abs(sent_message["completionRate"] - 67) < 1  # 3개 중 2개 완료 (required만, 반올림 고려)
        assert "fieldGroups" in sent_message
        
        # 수집 상태 확인
        completion_status = sent_message["completionStatus"]
        assert completion_status["loan_purpose_confirmed"] == True
        assert completion_status["marital_status"] == True
        assert completion_status["annual_income"] == False
        assert completion_status["spouse_income"] == False

    @pytest.mark.asyncio
    async def test_field_transformation(self, mock_websocket, sample_agent_state):
        """필드 변환 로직 테스트"""
        
        await send_slot_filling_update(mock_websocket, sample_agent_state)
        
        sent_message = mock_websocket.send_json.call_args[0][0]
        required_fields = sent_message["requiredFields"]
        
        # 필드 변환 확인
        for field in required_fields:
            assert "key" in field
            assert "displayName" in field
            assert "type" in field
            assert "required" in field
            
            if field["type"] == "choice":
                assert "choices" in field
            if field["type"] == "number":
                assert "unit" in field
            if "depends_on" in field:
                assert "dependsOn" in field  # camelCase 변환 확인

    @pytest.mark.asyncio
    async def test_empty_scenario_data(self, mock_websocket):
        """빈 시나리오 데이터 테스트"""
        
        empty_state = {
            "current_product_type": "didimdol",
            "active_scenario_data": None,
            "collected_product_info": {}
        }
        
        await send_slot_filling_update(mock_websocket, empty_state)
        
        # 빈 시나리오 데이터일 때는 전송하지 않음
        mock_websocket.send_json.assert_not_called()

    def test_update_condition_logic(self):
        """업데이트 조건 로직 테스트"""
        
        # 정보 변경 시 업데이트 필요
        assert should_send_slot_filling_update(
            info_changed=True,
            scenario_changed=False,
            product_type_changed=False,
            scenario_active=True,
            is_info_collection_stage=False
        ) == True
        
        # 시나리오 변경 시 업데이트 필요
        assert should_send_slot_filling_update(
            info_changed=False,
            scenario_changed=True,
            product_type_changed=False,
            scenario_active=True,
            is_info_collection_stage=False
        ) == True
        
        # 상품 타입 변경 시 업데이트 필요
        assert should_send_slot_filling_update(
            info_changed=False,
            scenario_changed=False,
            product_type_changed=True,
            scenario_active=True,
            is_info_collection_stage=False
        ) == True
        
        # 정보 수집 단계에서 업데이트 필요
        assert should_send_slot_filling_update(
            info_changed=False,
            scenario_changed=False,
            product_type_changed=False,
            scenario_active=True,
            is_info_collection_stage=True
        ) == True
        
        # 모든 조건이 False일 때는 업데이트 불필요
        assert should_send_slot_filling_update(
            info_changed=False,
            scenario_changed=False,
            product_type_changed=False,
            scenario_active=False,
            is_info_collection_stage=False
        ) == False

    def test_info_collection_stages(self):
        """정보 수집 단계 상수 테스트"""
        
        expected_stages = {
            "info_collection_guidance", 
            "process_collected_info",
            "ask_missing_info_group1", 
            "ask_missing_info_group2", 
            "ask_missing_info_group3"
        }
        
        assert INFO_COLLECTION_STAGES == expected_stages

    @pytest.mark.asyncio
    async def test_completion_rate_calculation(self, mock_websocket, sample_scenario_data):
        """완료율 계산 테스트"""
        
        test_cases = [
            # (수집된 정보, 예상 완료율)
            ({}, 0),  # 아무것도 수집 안됨
            ({"loan_purpose_confirmed": True}, 33),  # 1/3 완료
            ({"loan_purpose_confirmed": True, "marital_status": "미혼"}, 67),  # 2/3 완료
            ({"loan_purpose_confirmed": True, "marital_status": "미혼", "annual_income": 5000}, 100),  # 3/3 완료
        ]
        
        for collected_info, expected_rate in test_cases:
            state = {
                "current_product_type": "didimdol",
                "active_scenario_data": sample_scenario_data,
                "collected_product_info": collected_info
            }
            
            mock_websocket.reset_mock()
            await send_slot_filling_update(mock_websocket, state)
            
            sent_message = mock_websocket.send_json.call_args[0][0]
            assert abs(sent_message["completionRate"] - expected_rate) < 1  # 반올림 오차 허용

    @pytest.mark.asyncio
    async def test_websocket_error_handling(self, sample_agent_state):
        """WebSocket 에러 처리 테스트"""
        
        # WebSocket 에러 발생 시나리오
        mock_websocket = AsyncMock()
        mock_websocket.send_json.side_effect = Exception("WebSocket connection lost")
        
        # 에러가 발생해도 예외를 던지지 않고 로그만 출력해야 함
        try:
            await send_slot_filling_update(mock_websocket, sample_agent_state)
        except Exception as e:
            pytest.fail(f"send_slot_filling_update should handle errors gracefully, but raised: {e}")

    @pytest.mark.asyncio
    async def test_large_message_optimization(self, mock_websocket, sample_scenario_data):
        """대용량 메시지 최적화 테스트"""
        
        # 많은 필드를 가진 시나리오 생성
        large_scenario = sample_scenario_data.copy()
        large_scenario["required_info_fields"] = []
        
        # 100개의 필드 생성
        for i in range(100):
            large_scenario["required_info_fields"].append({
                "key": f"field_{i}",
                "display_name": f"필드 {i}",
                "type": "text",
                "required": True,
                "description": f"테스트 필드 {i}의 설명" * 10  # 긴 설명
            })
        
        state = {
            "current_product_type": "didimdol",
            "active_scenario_data": large_scenario,
            "collected_product_info": {}
        }
        
        await send_slot_filling_update(mock_websocket, state)
        
        sent_message = mock_websocket.send_json.call_args[0][0]
        
        # 메시지 크기 확인 (JSON 직렬화 후)
        message_size = len(json.dumps(sent_message, ensure_ascii=False))
        print(f"Large message size: {message_size} bytes")
        
        # 메시지가 너무 크지 않은지 확인 (예: 1MB 미만)
        assert message_size < 1024 * 1024, f"Message too large: {message_size} bytes"

    def test_field_groups_processing(self, sample_scenario_data):
        """필드 그룹 처리 테스트"""
        
        field_groups = sample_scenario_data["field_groups"]
        
        # 모든 필드가 그룹에 포함되어 있는지 확인
        all_fields_in_groups = set()
        for group in field_groups:
            all_fields_in_groups.update(group["fields"])
        
        required_field_keys = {field["key"] for field in sample_scenario_data["required_info_fields"]}
        
        assert all_fields_in_groups == required_field_keys


class TestSlotFillingEdgeCases:
    """Slot Filling 엣지 케이스 테스트"""
    
    @pytest.mark.asyncio
    async def test_malformed_scenario_data(self):
        """잘못된 형식의 시나리오 데이터 테스트"""
        
        mock_websocket = AsyncMock()
        
        malformed_cases = [
            # 필수 필드 누락
            {
                "current_product_type": "didimdol",
                "active_scenario_data": {
                    "required_info_fields": [
                        {"key": "test_field"}  # display_name, type 등 누락
                    ]
                },
                "collected_product_info": {}
            },
            # 타입 불일치
            {
                "current_product_type": "didimdol",
                "active_scenario_data": {
                    "required_info_fields": "not_a_list"  # 리스트가 아님
                },
                "collected_product_info": {}
            }
        ]
        
        for malformed_state in malformed_cases:
            mock_websocket.reset_mock()
            
            # 에러가 발생해도 크래시하지 않아야 함
            try:
                await send_slot_filling_update(mock_websocket, malformed_state)
            except Exception as e:
                pytest.fail(f"Should handle malformed data gracefully, but raised: {e}")

    @pytest.mark.asyncio
    async def test_circular_dependencies(self):
        """순환 의존성 테스트"""
        
        circular_scenario = {
            "required_info_fields": [
                {
                    "key": "field_a",
                    "display_name": "필드 A",
                    "type": "text",
                    "required": True,
                    "depends_on": {"field": "field_b", "value": "some_value"}
                },
                {
                    "key": "field_b", 
                    "display_name": "필드 B",
                    "type": "text",
                    "required": True,
                    "depends_on": {"field": "field_a", "value": "some_value"}
                }
            ]
        }
        
        state = {
            "current_product_type": "didimdol",
            "active_scenario_data": circular_scenario,
            "collected_product_info": {}
        }
        
        # 순환 의존성이 있어도 처리할 수 있어야 함
        mock_websocket = AsyncMock()
        await send_slot_filling_update(mock_websocket, state)
        mock_websocket.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_updates(self, sample_agent_state):
        """동시 업데이트 테스트"""
        
        # 동시에 여러 업데이트 요청
        mock_websocket = AsyncMock()
        tasks = []
        for i in range(10):
            task = send_slot_filling_update(mock_websocket, sample_agent_state)
            tasks.append(task)
        
        # 모든 업데이트가 완료되어야 함
        await asyncio.gather(*tasks)
        
        # 10번 호출되었는지 확인
        assert mock_websocket.send_json.call_count == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
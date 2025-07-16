"""
프롬프트 로더 - YAML 파일에서 프롬프트 로드
"""

import yaml
import os
from pathlib import Path
from typing import Dict, Any

def load_yaml_file(file_path: str) -> Dict[str, Any]:
    """YAML 파일 로드"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Warning: Prompt file not found: {file_path}")
        return {}
    except Exception as e:
        print(f"Error loading prompt file {file_path}: {e}")
        return {}

def load_all_prompts() -> Dict[str, Any]:
    """모든 프롬프트 파일 로드"""
    config_dir = Path(__file__).parent
    prompts = {}
    
    # YAML 파일 로드
    yaml_files = [
        "main_agent_prompts.yaml",
        "qa_agent_prompts.yaml", 
        "scenario_agent_prompts.yaml",
        "service_selection_prompts.yaml",
        "verification_prompts.yaml",
        "entity_extraction_prompts.yaml",
        "intent_classification_prompts.yaml"
    ]
    
    for yaml_file in yaml_files:
        file_path = config_dir / yaml_file
        if file_path.exists():
            prompts.update(load_yaml_file(str(file_path)))
    
    return prompts

# 전역 프롬프트 딕셔너리
ALL_PROMPTS = load_all_prompts()
# backend/app/agents/__init__.py

from .entity_agent import entity_agent, EntityRecognitionAgent
from .info_modification_agent import InfoModificationAgent

__all__ = [
    'entity_agent',
    'EntityRecognitionAgent',
    'InfoModificationAgent'
]
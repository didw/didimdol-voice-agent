# backend/app/agents/__init__.py

from .entity_agent import entity_agent, EntityRecognitionAgent
from .internet_banking_agent import internet_banking_agent, InternetBankingAgent
from .check_card_agent import check_card_agent, CheckCardAgent
from .info_modification_agent import InfoModificationAgent

__all__ = [
    'entity_agent',
    'EntityRecognitionAgent',
    'internet_banking_agent',
    'InternetBankingAgent',
    'check_card_agent',
    'CheckCardAgent',
    'InfoModificationAgent'
]
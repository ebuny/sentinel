import os
from pydantic_settings import BaseSettings
from pydantic import model_validator
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Operating Mode
    MOCK_MODE: bool = True  # True by default as requested to use preloaded mock keys
    
    # API Keys & Credentials
    CMC_API_KEY: str = "MOCK_CMC_API_KEY_SENTINEL_2026"
    TWAK_ACCESS_ID: str = "MOCK_TWAK_ACCESS_ID"
    TWAK_HMAC_SECRET: str = "MOCK_TWAK_HMAC_SECRET"
    IPFS_JWT: str = "MOCK_IPFS_JWT"
    
    # On-Chain / Web3
    AGENT_PRIVATE_KEY: str = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    RPC_URL: str = "https://data-seed-prebsc-1-s1.binance.org:8545/"  # BSC Testnet Default
    
    # Contract Addresses (Mock or official deployments)
    ERC8004_REGISTRY_ADDR: str = "0x8004000000000000000000000000000000000000"
    ERC8183_COMMERCE_ADDR: str = "0x8183000000000000000000000000000000000000"
    
    # Server configuration
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    
    # Agent service settings
    AGENT_SERVICE_PRICE: float = 0.01  # BNB price for hiring agent jobs
    AGENT_DISPUTE_WINDOW_SECONDS: int = 60  # Short for demo/test purposes
    AGENT_STRATEGY_COOLDOWN_SECONDS: int = 3600  # Default to 1 hour strategy cooldown
    
    @model_validator(mode="after")
    def validate_secrets(self) -> 'Settings':
        if not self.MOCK_MODE:
            mock_key = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            if self.AGENT_PRIVATE_KEY == mock_key:
                raise ValueError(
                    "Security Risk: Default mock AGENT_PRIVATE_KEY detected in config.py. "
                    "You must override it in .env when running with MOCK_MODE=False."
                )
        return self
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

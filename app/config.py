import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# Force API-key-only mode — must be set before any google.genai imports
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
os.environ.setdefault("GOOGLE_API_KEY", "")


@dataclass
class AgentConfig:
    # Reads model from environment GEMINI_MODEL. Default gemini-2.5-flash.
    model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    mcp_server_port: int = 8090
    max_iterations: int = 3
    pii_redaction_enabled: bool = True
    injection_detection_enabled: bool = True

config = AgentConfig()

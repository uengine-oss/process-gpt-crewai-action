import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        
        # CrewAI 텔레메트리 설정
        telemetry_mode = os.getenv("TELEMETRY_MODE", "disabled")  # disabled, custom, default
        
        if telemetry_mode == "disabled":
            os.environ["OTEL_SDK_DISABLED"] = "true"
        elif telemetry_mode == "custom":
            # 자체 텔레메트리 수집기로 전송
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = os.getenv("CUSTOM_TELEMETRY_ENDPOINT", "http://localhost:4317")
            os.environ["OTEL_SERVICE_NAME"] = "process-gpt-crewai"
            os.environ["OTEL_RESOURCE_ATTRIBUTES"] = "service.name=process-gpt,service.version=1.0"
        # telemetry_mode == "default"면 CrewAI 기본 설정 사용

settings = Settings() 
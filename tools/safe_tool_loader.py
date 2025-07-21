import os
import json
import logging
import time
import shutil
import subprocess
from pathlib import Path
from mcp.client.stdio import StdioServerParameters
from crewai_tools import MCPServerAdapter
# ============================================================================
# 설정 및 초기화
# ============================================================================

# 로거 설정
logger = logging.getLogger(__name__)

# ============================================================================
# 도구 로더 클래스
# ============================================================================

class SafeToolLoader:
    """MCP 기반 툴 로더 (로컬 STDIO 방식) - 여러 서버 설정 지원"""

    def __init__(self):
        # mcp.json 로드 및 allowed_tools 초기화
        config_path = Path(__file__).resolve().parents[1] / "config" / "mcp.json"
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
            self.config = cfg
            # mcpServers 키 목록을 허용 도구로 사용
            self.allowed_tools = list(cfg.get("mcpServers", {}).keys())
            logger.info(f"✅ SafeToolLoader 초기화 완료 (허용 도구: {self.allowed_tools})")
            print(f"🔧 SafeToolLoader 초기화: {self.allowed_tools}")
        except Exception as e:
            logger.error(f"❌ SafeToolLoader config 로드 실패: {e}")
            print(f"❌ SafeToolLoader config 로드 실패: {e}")
            self.config = {"mcpServers": {}}
            self.allowed_tools = []

    def _find_npx_command(self):
        """Windows에서 npx 명령어 경로를 찾습니다."""
        possible_commands = ["npx", "npx.cmd", "npx.ps1"]
        
        for cmd in possible_commands:
            if shutil.which(cmd):
                logger.info(f"✅ npx 명령어 발견: {cmd}")
                return cmd
                
        # PATH에서 찾지 못한 경우 일반적인 설치 경로 확인
        common_paths = [
            os.path.expanduser("~/AppData/Roaming/npm/npx.cmd"),
            "C:/Program Files/nodejs/npx.cmd",
            "C:/Program Files (x86)/nodejs/npx.cmd"
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"✅ npx 경로 발견: {path}")
                return path
                
        logger.error("❌ npx 명령어를 찾을 수 없습니다. Node.js가 설치되어 있고 PATH에 추가되어 있는지 확인하세요.")
        return None

    def warmup_server(self, server_key):
        """MCP 서버 사전 웜업 (패키지 다운로드 및 준비)"""
        try:
            logger.info(f"🔥 {server_key} 서버 웜업 시작...")
            print(f"🔥 {server_key} 서버 웜업 시작...")
            server_cfg = self.config.get("mcpServers", {}).get(server_key, {})
            
            if server_cfg.get("command") == "npx":
                # npx 명령어 경로 확인
                npx_cmd = self._find_npx_command()
                if not npx_cmd:
                    logger.warning(f"⚠️ npx를 찾을 수 없어 {server_key} 웜업 건너뜀")
                    print(f"⚠️ npx를 찾을 수 없어 {server_key} 웜업 건너뜀")
                    return
                
                args = server_cfg.get("args", [])
                if args and args[0] == "-y":
                    package = args[1] if len(args) > 1 else ""
                    logger.info(f"📦 {package} 패키지 캐시 확인 중...")
                    print(f"📦 {package} 패키지 캐시 확인 중...")
                    
                    # 캐시 확인을 위한 빠른 테스트
                    result = subprocess.run([npx_cmd, "-y", package, "--help"], 
                                          capture_output=True, timeout=10, text=True, 
                                          shell=True)  # Windows에서 shell=True 추가
                    
                    if result.returncode == 0:
                        logger.info(f"✅ {package} 패키지 캐시됨 (빠른 로딩 가능)")
                        print(f"✅ {package} 패키지 캐시됨")
                    else:
                        logger.info(f"📥 {package} 패키지 다운로드 중... (첫 실행)")
                        print(f"📥 {package} 패키지 다운로드 중...")
                        # 실제 다운로드 (더 긴 타임아웃)
                        subprocess.run([npx_cmd, "-y", package, "--help"], 
                                     capture_output=True, timeout=60, shell=True)
                        logger.info(f"✅ {package} 패키지 준비 완료")
                        print(f"✅ {package} 패키지 준비 완료")
                    
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️ {server_key} 웜업 타임아웃 (패키지 다운로드 중일 수 있음)")
            print(f"⚠️ {server_key} 웜업 타임아웃")
        except Exception as e:
            logger.warning(f"⚠️ {server_key} 웜업 실패 (무시됨): {e}")
            print(f"⚠️ {server_key} 웜업 실패: {e}")

    def create_tools_from_names(self, tool_names):
        """지정된 도구 이름으로 MCP 툴을 로드합니다."""
        if isinstance(tool_names, str):
            # 쉼표로 구분된 문자열인 경우 분리하여 리스트로 변환
            tool_names = [t.strip() for t in tool_names.split(',') if t.strip()]

        tools = []
        for name in tool_names:
            key = name.strip().lower()
            # '-mcp' 접미사 제거하여 설정 키와 매칭
            server_key = key[:-4] if key.endswith("-mcp") else key
            if server_key in self.allowed_tools:
                # 사전 웜업 실행
                self.warmup_server(server_key)
                tools.extend(self._load_mcp_server(server_key))
            else:
                logger.warning(f"⚠️ 지원하지 않는 도구 요청: {name}")
        return tools

    def _load_mcp_server(self, server_key):
        """지정된 MCP 서버(server_key) 도구 로드 (로컬 STDIO 방식)"""
        max_retries = 2
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"📡 {server_key}-mcp 서버 로드 시도 {attempt + 1}/{max_retries}")
                print(f"📡 {server_key}-mcp 서버 로드 시도 {attempt + 1}/{max_retries}")
                
                server_cfg = self.config.get("mcpServers", {}).get(server_key, {})
                
                # Windows에서 npx 명령어 처리
                command = server_cfg.get("command")
                if command == "npx":
                    npx_cmd = self._find_npx_command()
                    if not npx_cmd:
                        raise Exception("npx 명령어를 찾을 수 없습니다")
                    command = npx_cmd
                
                # 환경 변수 병합 (Service Role Key 포함)
                env_vars = os.environ.copy()
                env_vars.update(server_cfg.get("env", {}))
                # 타임아웃 옵션 읽기 (초 단위)
                timeout = server_cfg.get("timeout", 30)  # 기본값 30초
                
                logger.info(f"⏱️ 타임아웃 설정: {timeout}초")
                print(f"⏱️ 타임아웃: {timeout}초")
                logger.info(f"🔧 명령어: {command} {' '.join(server_cfg.get('args', []))}")
                print(f"🔧 명령어: {command} {' '.join(server_cfg.get('args', []))}")
                
                # StdioServerParameters 인자 설정
                params_kwargs = {
                    "command": command,
                    "args": server_cfg.get("args", []),
                    "env": env_vars
                }
                if timeout is not None:
                    params_kwargs["timeout"] = timeout

                params = StdioServerParameters(**params_kwargs)
                
                # MCPServerAdapter를 통해 툴 로드
                adapter = MCPServerAdapter(params)
                logger.info(f"✅ {server_key}-mcp 도구 로드 성공 (timeout={timeout})")
                print(f"✅ {server_key}-mcp 도구 로드 성공! 툴 개수: {len(adapter.tools)}")
                return adapter.tools

            except Exception as e:
                logger.error(f"❌ [{server_key}-mcp 로드 시도 {attempt + 1}] 오류: {e}")
                print(f"❌ [{server_key}-mcp 로드 시도 {attempt + 1}] 오류: {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"⏳ {retry_delay}초 후 재시도...")
                    print(f"⏳ {retry_delay}초 후 재시도...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"❌ [{server_key}-mcp 로드] 모든 재시도 실패")
                    print(f"❌ [{server_key}-mcp 로드] 모든 재시도 실패")
                    
        return []

"""테스트 공통 설정 - backend 패키지 import 경로 추가."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

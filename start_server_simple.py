#!/usr/bin/env python3
"""
간단한 서버 시작 스크립트
"""
import subprocess
import sys
import os

def start_server():
    """서버 시작"""
    print("🚀 AI 토론 시뮬레이터 서버 시작...")
    print("📁 현재 디렉토리:", os.getcwd())
    
    try:
        # 서버 시작
        subprocess.run([
            sys.executable, 
            "final_web_app.py"
        ], check=True)
    except KeyboardInterrupt:
        print("\n⏹️ 서버 중지됨")
    except Exception as e:
        print(f"❌ 서버 시작 실패: {e}")
        
        # 대체 방법
        print("🔄 대체 방법으로 시도...")
        subprocess.run([
            "uvicorn", 
            "final_web_app:app", 
            "--host", "0.0.0.0", 
            "--port", "8003",
            "--reload"
        ])

if __name__ == "__main__":
    start_server()
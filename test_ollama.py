#!/usr/bin/env python3
"""
Ollama 서버 연결 테스트 스크립트
"""

import httpx
import asyncio
import json

async def test_ollama_connection():
    """Ollama 서버 연결 테스트"""
    print("🔍 Ollama 서버 테스트 시작...\n")
    
    # 1. 서버 상태 확인
    print("1. 서버 상태 확인:")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = data.get('models', [])
                print(f"   ✅ Ollama 서버 실행 중")
                print(f"   ✅ 사용 가능한 모델 수: {len(models)}")
                if models:
                    print("   📋 모델 목록:")
                    for model in models[:5]:  # 최대 5개만 표시
                        print(f"      - {model.get('name')}")
                else:
                    print("   ⚠️  설치된 모델이 없습니다.")
                    print("   💡 'ollama pull llama3.2:3b' 명령으로 모델을 설치하세요.")
            else:
                print(f"   ❌ 서버 응답 오류: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Ollama 서버에 연결할 수 없습니다: {e}")
        print("   💡 'ollama serve' 명령을 실행하세요.")
        return False
    
    # 2. Chat API 테스트
    print("\n2. Chat API 테스트:")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "model": "llama3.2:3b",
                "messages": [
                    {"role": "system", "content": "당신은 친절한 AI 어시스턴트입니다."},
                    {"role": "user", "content": "안녕하세요? 간단히 인사해주세요."}
                ],
                "stream": False
            }
            
            print("   🚀 테스트 메시지 전송 중...")
            response = await client.post(
                "http://localhost:11434/api/chat",
                json=payload
            )
            
            if response.status_code == 200:
                data = response.json()
                message = data.get('message', {}).get('content', '')
                print(f"   ✅ 응답 수신: {message[:100]}...")
                return True
            else:
                print(f"   ❌ API 오류: {response.status_code}")
                print(f"   응답: {response.text}")
    except httpx.TimeoutException:
        print("   ❌ 시간 초과 - 모델이 로드되지 않았을 수 있습니다.")
        print("   💡 'ollama run llama3.2:3b' 명령으로 모델을 먼저 실행해보세요.")
    except Exception as e:
        print(f"   ❌ Chat API 오류: {e}")
    
    return False

async def test_streaming():
    """스트리밍 API 테스트"""
    print("\n3. 스트리밍 API 테스트:")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "model": "llama3.2:3b",
                "messages": [
                    {"role": "user", "content": "1부터 5까지 세어주세요."}
                ],
                "stream": True
            }
            
            print("   🚀 스트리밍 테스트 중...")
            full_response = ""
            
            async with client.stream('POST', "http://localhost:11434/api/chat", json=payload) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if 'message' in data:
                                content = data['message'].get('content', '')
                                full_response += content
                                print(f"   📝 스트리밍: {content}", end='', flush=True)
                        except json.JSONDecodeError:
                            pass
            
            print(f"\n   ✅ 스트리밍 완료")
            return True
            
    except Exception as e:
        print(f"   ❌ 스트리밍 오류: {e}")
        return False

async def main():
    """메인 테스트 함수"""
    print("=" * 50)
    print("🤖 Ollama 서버 종합 테스트")
    print("=" * 50)
    
    # 기본 연결 테스트
    connected = await test_ollama_connection()
    
    # 스트리밍 테스트
    if connected:
        await test_streaming()
    
    print("\n" + "=" * 50)
    print("테스트 완료!")
    
    if not connected:
        print("\n⚠️  Ollama 서버 설정 가이드:")
        print("1. Ollama 설치: https://ollama.ai")
        print("2. 서버 시작: ollama serve")
        print("3. 모델 설치: ollama pull llama3.2:3b")
        print("4. 이 스크립트 다시 실행")

if __name__ == "__main__":
    asyncio.run(main())
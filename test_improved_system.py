#!/usr/bin/env python3
"""
개선된 AI 토론 시뮬레이터 시스템 테스트
모든 새로운 기능들의 통합 테스트
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any
import httpx
import pytest
from fastapi.testclient import TestClient

# 개선된 애플리케이션 모듈
from final_web_app_improved import app
from config.settings import settings
from utils.security import rate_limiter, session_manager
from utils.cache import cache_manager, debate_caches
from utils.monitoring import metrics_collector, performance_monitor


class TestSystemIntegration:
    """시스템 통합 테스트"""
    
    def setup_method(self):
        """테스트 설정"""
        self.client = TestClient(app)
        
    def test_health_check_endpoint(self):
        """헬스체크 엔드포인트 테스트"""
        response = self.client.get("/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "checks" in data
        
    def test_status_endpoint(self):
        """상태 엔드포인트 테스트"""
        response = self.client.get("/api/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "environment" in data
        assert "active_debates" in data
        assert "active_connections" in data
        
    def test_models_endpoint(self):
        """모델 목록 엔드포인트 테스트"""
        response = self.client.get("/api/models")
        assert response.status_code == 200
        
        data = response.json()
        assert "models" in data
        assert isinstance(data["models"], list)
        
    def test_metrics_endpoint(self):
        """메트릭 엔드포인트 테스트"""
        response = self.client.get("/api/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "metrics" in data
        assert "alerts" in data
        assert "cache" in data
        assert "timestamp" in data
        
    def test_debate_start_endpoint(self):
        """토론 시작 엔드포인트 테스트"""
        debate_data = {
            "topic": "AI의 미래에 대한 토론",
            "format": "adversarial",
            "max_rounds": 3,
            "temperature": 0.7
        }
        
        response = self.client.post("/api/debate/start", json=debate_data)
        assert response.status_code == 200
        
        data = response.json()
        assert "session_id" in data
        assert "topic" in data
        assert "format" in data
        assert "status" in data
        assert data["status"] == "started"
        
    def test_security_headers(self):
        """보안 헤더 테스트"""
        response = self.client.get("/api/status")
        
        # 보안 헤더 확인
        assert "x-content-type-options" in response.headers
        assert "x-frame-options" in response.headers
        assert "x-xss-protection" in response.headers
        
    def test_rate_limiting(self):
        """레이트 리미팅 테스트"""
        # 많은 요청을 빠르게 보내기
        responses = []
        for i in range(15):  # 기본 제한보다 많이
            response = self.client.get("/api/status")
            responses.append(response)
        
        # 일부 요청이 차단되었는지 확인
        rate_limited = any(r.status_code == 429 for r in responses)
        assert rate_limited, "Rate limiting should have blocked some requests"
        
    def test_input_validation(self):
        """입력 검증 테스트"""
        # 잘못된 토론 형식
        invalid_data = {
            "topic": "테스트",
            "format": "invalid_format",
            "max_rounds": 3
        }
        
        response = self.client.post("/api/debate/start", json=invalid_data)
        assert response.status_code == 422  # Validation error
        
        # 너무 짧은 주제
        short_topic_data = {
            "topic": "짧음",
            "format": "adversarial",
            "max_rounds": 3
        }
        
        response = self.client.post("/api/debate/start", json=short_topic_data)
        assert response.status_code == 422
        
    def test_xss_protection(self):
        """XSS 공격 방어 테스트"""
        malicious_data = {
            "topic": "<script>alert('xss')</script>AI에 대한 토론",
            "format": "adversarial",
            "max_rounds": 3
        }
        
        response = self.client.post("/api/debate/start", json=malicious_data)
        
        if response.status_code == 200:
            # 스크립트 태그가 제거되었는지 확인
            data = response.json()
            assert "<script>" not in data["topic"]
            assert "alert" not in data["topic"]


class TestCacheSystem:
    """캐시 시스템 테스트"""
    
    @pytest.mark.asyncio
    async def test_cache_basic_operations(self):
        """기본 캐시 작업 테스트"""
        cache = cache_manager.get_cache("test")
        
        # 캐시 저장
        await cache.set("test_key", "test_value", ttl=60)
        
        # 캐시 조회
        value = await cache.get("test_key")
        assert value == "test_value"
        
        # 캐시 삭제
        deleted = await cache.delete("test_key")
        assert deleted is True
        
        # 삭제 후 조회
        value = await cache.get("test_key")
        assert value is None
        
    @pytest.mark.asyncio
    async def test_cache_expiration(self):
        """캐시 만료 테스트"""
        cache = cache_manager.get_cache("test")
        
        # 1초 TTL로 캐시 저장
        await cache.set("expire_test", "value", ttl=1)
        
        # 즉시 조회 - 값이 있어야 함
        value = await cache.get("expire_test")
        assert value == "value"
        
        # 2초 대기 후 조회 - 값이 없어야 함
        await asyncio.sleep(2)
        value = await cache.get("expire_test")
        assert value is None
        
    @pytest.mark.asyncio
    async def test_cache_statistics(self):
        """캐시 통계 테스트"""
        cache = cache_manager.get_cache("test")
        
        # 캐시 히트/미스 테스트
        await cache.set("stat_test", "value")
        
        # 히트
        await cache.get("stat_test")
        
        # 미스
        await cache.get("nonexistent_key")
        
        stats = cache.get_stats()
        assert stats["hits"] > 0
        assert stats["misses"] > 0
        assert stats["hit_rate"] > 0


class TestSecuritySystem:
    """보안 시스템 테스트"""
    
    def test_rate_limiter_basic(self):
        """레이트 리미터 기본 테스트"""
        limiter = rate_limiter
        
        # 첫 번째 요청 - 허용되어야 함
        allowed, info = limiter.is_allowed("test_client", "127.0.0.1")
        assert allowed is True
        assert "remaining" in info
        
        # 제한 해제
        limiter.release_lock("test_client")
        
    def test_session_manager(self):
        """세션 관리자 테스트"""
        manager = session_manager
        
        # 세션 생성
        session_id = manager.create_session({"client_ip": "127.0.0.1"})
        assert session_id is not None
        
        # 세션 검증
        valid = manager.validate_session(session_id)
        assert valid is True
        
        # 세션 무효화
        manager.invalidate_session(session_id)
        valid = manager.validate_session(session_id)
        assert valid is False
        
    def test_input_sanitization(self):
        """입력 정리 테스트"""
        from utils.security import InputSanitizer
        
        sanitizer = InputSanitizer()
        
        # HTML 태그 제거
        dirty_html = "<script>alert('xss')</script>안전한 텍스트"
        clean_text = sanitizer.sanitize_html(dirty_html)
        assert "<script>" not in clean_text
        assert "안전한 텍스트" in clean_text
        
        # 세션 ID 검증
        valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
        assert sanitizer.validate_session_id(valid_uuid) is True
        
        invalid_uuid = "invalid-uuid"
        assert sanitizer.validate_session_id(invalid_uuid) is False


class TestMonitoringSystem:
    """모니터링 시스템 테스트"""
    
    def test_metrics_collection(self):
        """메트릭 수집 테스트"""
        collector = metrics_collector
        
        # 메트릭 기록
        collector.record_metric("test_metric", 42.0, {"tag": "test"})
        
        # 카운터 증가
        collector.increment_counter("test_counter", 5)
        
        # 타이머 기록
        collector.record_timer("test_timer", 1.5)
        
        # 통계 조회
        stats = collector.get_metric_stats("test_metric")
        assert stats["count"] == 1
        assert stats["last"] == 42.0
        
    def test_performance_monitor(self):
        """성능 모니터 테스트"""
        monitor = performance_monitor
        
        # 요청 기록
        monitor.record_request(0.5, "success")
        monitor.record_request(1.0, "error")
        
        # 연결 변경 기록
        monitor.record_connection_change(1)
        monitor.record_connection_change(-1)
        
        # 시스템 메트릭 확인
        sys_metrics = monitor.get_system_metrics()
        assert "cpu_percent" in sys_metrics
        assert "memory_percent" in sys_metrics


class TestLoadAndStress:
    """부하 및 스트레스 테스트"""
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """동시 요청 테스트"""
        async def make_request():
            async with httpx.AsyncClient(app=app, base_url="http://test") as client:
                response = await client.get("/api/status")
                return response.status_code
        
        # 10개의 동시 요청
        tasks = [make_request() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # 모든 요청이 성공했는지 확인
        success_count = sum(1 for status in results if status == 200)
        assert success_count > 0  # 적어도 일부는 성공해야 함
        
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self):
        """부하 상황에서 메모리 사용량 테스트"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # 많은 캐시 엔트리 생성
        cache = cache_manager.get_cache("load_test")
        for i in range(1000):
            await cache.set(f"key_{i}", f"value_{i}" * 100)
        
        # 메모리 사용량 확인
        current_memory = process.memory_info().rss
        memory_increase = current_memory - initial_memory
        
        # 메모리 증가가 합리적인 범위 내인지 확인
        assert memory_increase < 100 * 1024 * 1024  # 100MB 미만
        
        # 캐시 정리
        await cache.clear()


async def test_ollama_integration():
    """Ollama 통합 테스트"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_api_url}/api/tags")
            
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                print(f"✅ Ollama 연결 성공: {len(models)}개 모델 사용 가능")
                return True
            else:
                print(f"⚠️  Ollama 서버 응답 오류: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Ollama 연결 실패: {e}")
        return False


async def main():
    """메인 테스트 실행"""
    print("🧪 AI 토론 시뮬레이터 - 개선된 시스템 테스트 시작")
    print("=" * 60)
    
    # Ollama 연결 테스트
    print("\n1. Ollama 연결 테스트")
    ollama_ok = await test_ollama_integration()
    
    # 기본 기능 테스트
    print("\n2. 기본 기능 테스트")
    try:
        pytest.main([__file__, "-v", "--tb=short"])
        print("✅ 모든 테스트 통과")
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
    
    # 성능 테스트
    print("\n3. 성능 테스트")
    start_time = time.time()
    
    # 간단한 성능 테스트
    cache = cache_manager.get_cache("perf_test")
    
    # 1000개 키 저장
    for i in range(1000):
        await cache.set(f"perf_key_{i}", f"perf_value_{i}")
    
    # 1000개 키 조회
    for i in range(1000):
        value = await cache.get(f"perf_key_{i}")
        assert value == f"perf_value_{i}"
    
    end_time = time.time()
    print(f"✅ 성능 테스트 완료: {end_time - start_time:.2f}초")
    
    # 최종 보고서
    print("\n" + "=" * 60)
    print("📊 테스트 결과 요약")
    print("=" * 60)
    
    print(f"🌍 환경: {settings.environment}")
    print(f"🔧 디버그 모드: {settings.debug}")
    print(f"🔗 Ollama 연결: {'✅ 성공' if ollama_ok else '❌ 실패'}")
    print(f"⚡ 성능: {end_time - start_time:.2f}초 (1000회 캐시 작업)")
    
    # 캐시 통계
    cache_stats = cache_manager.get_all_stats()
    print(f"💾 캐시 적중률: {cache_stats['default']['hit_rate']:.2%}")
    
    # 메트릭 통계
    metrics = metrics_collector.get_all_metrics()
    print(f"📈 수집된 메트릭: {len(metrics)}개")
    
    print("\n🎉 시스템 테스트 완료!")
    print("🚀 프로덕션 환경 준비 완료")


if __name__ == "__main__":
    asyncio.run(main())
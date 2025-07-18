"""
캐싱 시스템 구현
성능 최적화를 위한 메모리 기반 캐시
"""

import asyncio
import hashlib
import json
import pickle
import time
from typing import Any, Dict, Optional, Callable, Union
from datetime import datetime, timedelta
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


class CacheEntry:
    """캐시 엔트리 클래스"""
    
    def __init__(self, value: Any, ttl: int = 3600):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.access_count = 0
        self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        """만료 여부 확인"""
        return time.time() - self.created_at > self.ttl
    
    def access(self) -> Any:
        """값 접근 (통계 업데이트)"""
        self.access_count += 1
        self.last_accessed = time.time()
        return self.value
    
    def __repr__(self):
        return f"CacheEntry(value={type(self.value).__name__}, ttl={self.ttl}, access_count={self.access_count})"


class SimpleCache:
    """간단한 메모리 기반 캐시"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0
        self.lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """캐시에서 값 가져오기"""
        async with self.lock:
            if key in self.cache:
                entry = self.cache[key]
                
                # 만료 확인
                if entry.is_expired():
                    del self.cache[key]
                    self.misses += 1
                    return None
                
                # LRU 업데이트
                self.cache.move_to_end(key)
                self.hits += 1
                return entry.access()
            
            self.misses += 1
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """캐시에 값 저장"""
        async with self.lock:
            if ttl is None:
                ttl = self.default_ttl
            
            # 크기 제한 확인
            if len(self.cache) >= self.max_size and key not in self.cache:
                # 가장 오래된 항목 제거
                self.cache.popitem(last=False)
            
            self.cache[key] = CacheEntry(value, ttl)
            self.cache.move_to_end(key)
    
    async def delete(self, key: str) -> bool:
        """캐시에서 키 삭제"""
        async with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False
    
    async def clear(self) -> None:
        """캐시 전체 정리"""
        async with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
    
    async def cleanup_expired(self) -> int:
        """만료된 항목 정리"""
        async with self.lock:
            expired_keys = [
                key for key, entry in self.cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                del self.cache[key]
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """캐시 통계 반환"""
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0
        
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'memory_usage': self._estimate_memory_usage()
        }
    
    def _estimate_memory_usage(self) -> int:
        """메모리 사용량 추정"""
        try:
            total_size = 0
            for key, entry in self.cache.items():
                total_size += len(key.encode('utf-8'))
                total_size += len(pickle.dumps(entry.value))
            return total_size
        except:
            return 0


class LRUCache:
    """LRU 캐시 구현"""
    
    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """값 가져오기"""
        async with self.lock:
            if key in self.cache:
                # 최근 사용으로 이동
                self.cache.move_to_end(key)
                return self.cache[key]
            return None
    
    async def set(self, key: str, value: Any) -> None:
        """값 저장"""
        async with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            elif len(self.cache) >= self.capacity:
                # 가장 오래된 항목 제거
                self.cache.popitem(last=False)
            
            self.cache[key] = value


class CacheManager:
    """캐시 관리자"""
    
    def __init__(self, default_ttl: int = 3600, max_size: int = 1000):
        self.default_cache = SimpleCache(max_size=max_size, default_ttl=default_ttl)
        self.specialized_caches: Dict[str, SimpleCache] = {}
        self.cleanup_task = None
    
    def get_cache(self, cache_name: str = "default") -> SimpleCache:
        """캐시 인스턴스 반환"""
        if cache_name == "default":
            return self.default_cache
        
        if cache_name not in self.specialized_caches:
            self.specialized_caches[cache_name] = SimpleCache()
        
        return self.specialized_caches[cache_name]
    
    async def start_cleanup_task(self, interval: int = 300):
        """정리 작업 시작"""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self._cleanup_loop(interval))
    
    async def stop_cleanup_task(self):
        """정리 작업 중지"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            self.cleanup_task = None
    
    async def _cleanup_loop(self, interval: int):
        """정리 루프"""
        while True:
            try:
                await asyncio.sleep(interval)
                
                # 기본 캐시 정리
                expired_count = await self.default_cache.cleanup_expired()
                
                # 전문 캐시 정리
                total_expired = expired_count
                for cache in self.specialized_caches.values():
                    total_expired += await cache.cleanup_expired()
                
                if total_expired > 0:
                    logger.info(f"Cleaned up {total_expired} expired cache entries")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")
    
    def get_all_stats(self) -> Dict[str, Any]:
        """모든 캐시 통계"""
        stats = {
            'default': self.default_cache.get_stats(),
            'specialized': {}
        }
        
        for name, cache in self.specialized_caches.items():
            stats['specialized'][name] = cache.get_stats()
        
        return stats


def cache_key(*args, **kwargs) -> str:
    """캐시 키 생성"""
    key_data = {
        'args': args,
        'kwargs': sorted(kwargs.items())
    }
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(key_string.encode()).hexdigest()


def cached(ttl: int = 3600, cache_name: str = "default"):
    """캐시 데코레이터"""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            cache = cache_manager.get_cache(cache_name)
            key = f"{func.__name__}:{cache_key(*args, **kwargs)}"
            
            # 캐시에서 확인
            cached_result = await cache.get(key)
            if cached_result is not None:
                return cached_result
            
            # 함수 실행
            result = await func(*args, **kwargs)
            
            # 캐시에 저장
            await cache.set(key, result, ttl)
            
            return result
        return wrapper
    return decorator


# 전역 캐시 매니저
cache_manager = CacheManager()


# 특화된 캐시 인스턴스들
class DebateCaches:
    """토론 관련 캐시들"""
    
    def __init__(self):
        self.arguments = cache_manager.get_cache("arguments")
        self.evaluations = cache_manager.get_cache("evaluations")
        self.models = cache_manager.get_cache("models")
        self.sessions = cache_manager.get_cache("sessions")
    
    async def cache_argument(self, agent_name: str, topic: str, argument: str, ttl: int = 1800):
        """논증 캐시"""
        key = f"arg:{agent_name}:{hashlib.md5(topic.encode()).hexdigest()}"
        await self.arguments.set(key, argument, ttl)
    
    async def get_cached_argument(self, agent_name: str, topic: str) -> Optional[str]:
        """캐시된 논증 조회"""
        key = f"arg:{agent_name}:{hashlib.md5(topic.encode()).hexdigest()}"
        return await self.arguments.get(key)
    
    async def cache_evaluation(self, argument_hash: str, evaluation: Dict[str, Any], ttl: int = 3600):
        """평가 결과 캐시"""
        key = f"eval:{argument_hash}"
        await self.evaluations.set(key, evaluation, ttl)
    
    async def get_cached_evaluation(self, argument_hash: str) -> Optional[Dict[str, Any]]:
        """캐시된 평가 조회"""
        key = f"eval:{argument_hash}"
        return await self.evaluations.get(key)


# 전역 토론 캐시
debate_caches = DebateCaches()
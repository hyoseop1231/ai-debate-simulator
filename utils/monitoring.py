"""
모니터링 및 메트릭 수집 시스템
"""

import asyncio
import time
import psutil
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
import threading

logger = logging.getLogger(__name__)


@dataclass
class MetricData:
    """메트릭 데이터 클래스"""
    name: str
    value: float
    timestamp: datetime
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'value': self.value,
            'timestamp': self.timestamp.isoformat(),
            'tags': self.tags
        }


class MetricsCollector:
    """메트릭 수집기"""
    
    def __init__(self, max_history: int = 1000):
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self.counters: Dict[str, int] = defaultdict(int)
        self.timers: Dict[str, List[float]] = defaultdict(list)
        self.lock = threading.Lock()
    
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """메트릭 기록"""
        with self.lock:
            metric = MetricData(
                name=name,
                value=value,
                timestamp=datetime.now(),
                tags=tags or {}
            )
            self.metrics[name].append(metric)
    
    def increment_counter(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
        """카운터 증가"""
        with self.lock:
            self.counters[name] += value
        self.record_metric(name, self.counters[name], tags)
    
    def record_timer(self, name: str, duration: float, tags: Optional[Dict[str, str]] = None):
        """타이머 기록"""
        with self.lock:
            self.timers[name].append(duration)
        self.record_metric(f"{name}_duration", duration, tags)
    
    def get_metric_stats(self, name: str) -> Dict[str, Any]:
        """메트릭 통계 반환"""
        with self.lock:
            if name not in self.metrics:
                return {}
            
            values = [m.value for m in self.metrics[name]]
            if not values:
                return {}
            
            return {
                'count': len(values),
                'min': min(values),
                'max': max(values),
                'avg': sum(values) / len(values),
                'last': values[-1] if values else 0,
                'recent_avg': sum(values[-10:]) / min(10, len(values)) if values else 0
            }
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """모든 메트릭 반환"""
        with self.lock:
            result = {}
            for name in self.metrics:
                result[name] = self.get_metric_stats(name)
            return result


class PerformanceMonitor:
    """성능 모니터링"""
    
    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector
        self.start_time = time.time()
        self.request_count = 0
        self.error_count = 0
        self.active_connections = 0
        self.monitoring_task = None
    
    def record_request(self, duration: float, status: str = "success"):
        """요청 기록"""
        self.request_count += 1
        self.metrics.record_timer("request_duration", duration)
        self.metrics.increment_counter("requests_total")
        
        if status == "error":
            self.error_count += 1
            self.metrics.increment_counter("errors_total")
        
        self.metrics.record_metric("requests_per_second", 
                                 self.request_count / (time.time() - self.start_time))
    
    def record_connection_change(self, change: int):
        """연결 수 변경 기록"""
        self.active_connections += change
        self.metrics.record_metric("active_connections", self.active_connections)
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """시스템 메트릭 수집"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available': memory.available,
                'memory_used': memory.used,
                'disk_percent': disk.percent,
                'disk_free': disk.free,
                'disk_used': disk.used,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            return {}
    
    async def start_monitoring(self, interval: int = 30):
        """모니터링 시작"""
        if self.monitoring_task is None:
            self.monitoring_task = asyncio.create_task(self._monitoring_loop(interval))
    
    async def stop_monitoring(self):
        """모니터링 중지"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None
    
    async def _monitoring_loop(self, interval: int):
        """모니터링 루프"""
        while True:
            try:
                await asyncio.sleep(interval)
                
                # 시스템 메트릭 수집
                system_metrics = self.get_system_metrics()
                for name, value in system_metrics.items():
                    if isinstance(value, (int, float)) and name != 'timestamp':
                        self.metrics.record_metric(f"system_{name}", value)
                
                # 에러율 계산
                error_rate = self.error_count / max(self.request_count, 1)
                self.metrics.record_metric("error_rate", error_rate)
                
                # 업타임 기록
                uptime = time.time() - self.start_time
                self.metrics.record_metric("uptime_seconds", uptime)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")


class HealthChecker:
    """헬스 체크 시스템"""
    
    def __init__(self):
        self.health_checks: Dict[str, Callable] = {}
        self.last_check_results: Dict[str, Dict[str, Any]] = {}
        self.check_task = None
    
    def register_check(self, name: str, check_func: Callable):
        """헬스 체크 등록"""
        self.health_checks[name] = check_func
    
    async def run_check(self, name: str) -> Dict[str, Any]:
        """단일 헬스 체크 실행"""
        if name not in self.health_checks:
            return {"status": "unknown", "error": "Check not found"}
        
        start_time = time.time()
        try:
            result = await self.health_checks[name]()
            duration = time.time() - start_time
            
            return {
                "status": "healthy" if result else "unhealthy",
                "duration": duration,
                "timestamp": datetime.now().isoformat(),
                "details": result if isinstance(result, dict) else {}
            }
        except Exception as e:
            duration = time.time() - start_time
            return {
                "status": "unhealthy",
                "duration": duration,
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """모든 헬스 체크 실행"""
        results = {}
        
        for name in self.health_checks:
            results[name] = await self.run_check(name)
        
        # 전체 상태 결정
        overall_status = "healthy"
        if any(result["status"] == "unhealthy" for result in results.values()):
            overall_status = "unhealthy"
        elif any(result["status"] == "unknown" for result in results.values()):
            overall_status = "degraded"
        
        self.last_check_results = results
        
        return {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "checks": results
        }
    
    async def start_periodic_checks(self, interval: int = 30):
        """주기적 헬스 체크 시작"""
        if self.check_task is None:
            self.check_task = asyncio.create_task(self._check_loop(interval))
    
    async def stop_periodic_checks(self):
        """주기적 헬스 체크 중지"""
        if self.check_task:
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass
            self.check_task = None
    
    async def _check_loop(self, interval: int):
        """헬스 체크 루프"""
        while True:
            try:
                await asyncio.sleep(interval)
                await self.run_all_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")


class AlertManager:
    """알림 관리자"""
    
    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector
        self.alert_rules: List[Dict[str, Any]] = []
        self.active_alerts: Dict[str, Dict[str, Any]] = {}
        self.alert_history: List[Dict[str, Any]] = []
        self.alert_task = None
    
    def add_alert_rule(self, name: str, condition: Callable, threshold: float, 
                      severity: str = "warning", message: str = ""):
        """알림 규칙 추가"""
        self.alert_rules.append({
            'name': name,
            'condition': condition,
            'threshold': threshold,
            'severity': severity,
            'message': message
        })
    
    async def check_alerts(self):
        """알림 확인"""
        current_time = datetime.now()
        
        for rule in self.alert_rules:
            try:
                # 조건 확인
                is_triggered = await rule['condition'](self.metrics, rule['threshold'])
                
                if is_triggered:
                    # 새로운 알림 또는 기존 알림 업데이트
                    if rule['name'] not in self.active_alerts:
                        alert = {
                            'name': rule['name'],
                            'severity': rule['severity'],
                            'message': rule['message'],
                            'triggered_at': current_time,
                            'count': 1
                        }
                        self.active_alerts[rule['name']] = alert
                        self.alert_history.append(alert.copy())
                        logger.warning(f"Alert triggered: {rule['name']} - {rule['message']}")
                    else:
                        self.active_alerts[rule['name']]['count'] += 1
                else:
                    # 알림 해제
                    if rule['name'] in self.active_alerts:
                        resolved_alert = self.active_alerts[rule['name']].copy()
                        resolved_alert['resolved_at'] = current_time
                        self.alert_history.append(resolved_alert)
                        del self.active_alerts[rule['name']]
                        logger.info(f"Alert resolved: {rule['name']}")
                        
            except Exception as e:
                logger.error(f"Alert check error for {rule['name']}: {e}")
    
    async def start_alert_monitoring(self, interval: int = 60):
        """알림 모니터링 시작"""
        if self.alert_task is None:
            self.alert_task = asyncio.create_task(self._alert_loop(interval))
    
    async def stop_alert_monitoring(self):
        """알림 모니터링 중지"""
        if self.alert_task:
            self.alert_task.cancel()
            try:
                await self.alert_task
            except asyncio.CancelledError:
                pass
            self.alert_task = None
    
    async def _alert_loop(self, interval: int):
        """알림 루프"""
        while True:
            try:
                await asyncio.sleep(interval)
                await self.check_alerts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Alert monitoring error: {e}")
    
    def get_alert_summary(self) -> Dict[str, Any]:
        """알림 요약 반환"""
        return {
            'active_alerts': len(self.active_alerts),
            'total_alerts': len(self.alert_history),
            'active_details': list(self.active_alerts.values()),
            'recent_history': self.alert_history[-10:]  # 최근 10개
        }


# 전역 모니터링 인스턴스
metrics_collector = MetricsCollector()
performance_monitor = PerformanceMonitor(metrics_collector)
health_checker = HealthChecker()
alert_manager = AlertManager(metrics_collector)


# 기본 알림 규칙들
async def high_error_rate_condition(metrics: MetricsCollector, threshold: float) -> bool:
    """높은 에러율 조건"""
    error_rate_stats = metrics.get_metric_stats("error_rate")
    return error_rate_stats.get('last', 0) > threshold

async def high_memory_usage_condition(metrics: MetricsCollector, threshold: float) -> bool:
    """높은 메모리 사용률 조건"""
    memory_stats = metrics.get_metric_stats("system_memory_percent")
    return memory_stats.get('last', 0) > threshold

async def high_response_time_condition(metrics: MetricsCollector, threshold: float) -> bool:
    """높은 응답시간 조건"""
    response_time_stats = metrics.get_metric_stats("request_duration")
    return response_time_stats.get('recent_avg', 0) > threshold


# 기본 알림 규칙 설정
def setup_default_alerts():
    """기본 알림 규칙 설정"""
    alert_manager.add_alert_rule(
        "high_error_rate",
        high_error_rate_condition,
        0.1,  # 10%
        "critical",
        "Error rate exceeded 10%"
    )
    
    alert_manager.add_alert_rule(
        "high_memory_usage",
        high_memory_usage_condition,
        85.0,  # 85%
        "warning",
        "Memory usage exceeded 85%"
    )
    
    alert_manager.add_alert_rule(
        "high_response_time",
        high_response_time_condition,
        5.0,  # 5초
        "warning",
        "Average response time exceeded 5 seconds"
    )
"""
P0: 健康检查、熔断器与降级策略

三大核心模块：
- health_checker:  定期巡检各子系统健康度
- circuit_breaker: 熔断器（连续失败自动切断）
- degradation:   三级服务降级策略
"""

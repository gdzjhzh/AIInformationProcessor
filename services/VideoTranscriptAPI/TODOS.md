# TODOS

## P2: API 速率限制

**What:** 加入基于 IP/Token 的简单速率限制，防止资源耗尽和暴力破解。

**Why:** 当前任何持有有效 Token 的用户可以无限提交任务，无效 Token 尝试无日志警告。

**Pros:** 安全基础设施，防止资源滥用。

**Cons:** 当前用户量小，优先级不高。

**Context:** 可用 FastAPI 的 slowapi 或自定义中间件。需决定限制粒度（每分钟/每小时）和限制值。

**Effort:** S（人工）→ S（CC）

**Priority:** P2

**Depends on:** 无

---

## P2: 内存缓存 TTL/LRU 限制

**What:** 为下载器内存缓存（generic.py 的 `_cached_video_info`）加入 TTL 或 LRU 限制。

**Why:** 当前内存缓存永不过期，长时间运行可能内存泄漏。

**Pros:** 防止内存泄漏，提高长期稳定性。

**Cons:** 改动小，风险低。

**Context:** 可用 `functools.lru_cache` 或 `cachetools.TTLCache`。建议 TTL=1h，maxsize=1000。

**Effort:** S（人工）→ S（CC）

**Priority:** P2

**Depends on:** 无

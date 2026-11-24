# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `trip_id` | text | 主键 |
| `account_id` | text | 账户号，账户日封顶按此字段归集 |
| `bike_id` | text | 业务字段 |
| `start_at` | datetime | 业务字段 |
| `end_at` | datetime | 业务字段 |
| `paused_minutes` | int | 业务字段 |
| `distance_m` | int | 业务字段 |
| `wallet_debit` | money | 实扣车费，签发时按额度拆为认收与待退 |
| `plan` | text | 业务字段 |

签发派生字段（整数分）：

| 字段 | 说明 |
|---|---|
| `recognized_cents` | 本批在账户日剩余额度内实际认收的车费 |
| `refund_cents` | 实扣中超出日封顶、需退回的部分，`debit - recognized` |
| `daily_cap_cents` | 同一账户每个自然日的认收封顶（默认 400 分） |
| `day_fares` | 跨日拆段后各自然日的应扣车费 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

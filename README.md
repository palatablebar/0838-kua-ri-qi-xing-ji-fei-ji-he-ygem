# 跨日骑行计费稽核

共享出行结算员处理跨日拆段与日封顶的本地工作台。样例、规则和复核记录都在项目内，不依赖外部服务。

## 启动

```bash
docker compose up --build
```

打开 `http://127.0.0.1:${PORT:-18520}`。默认端口见 `docker-compose.yml`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

## 操作

1. 在左侧选阶段，查看采信、整理、计算、判定和对账结果。
2. 选择 `dirty` 样例观察坏行和隔离原因。
3. 换 `clean` 样例执行批次，填写复核意见后签发。
4. 先执行并签发 `shared_a`，再执行并签发 `shared_b`：两批单看都不超额，但同一账户日合并后触顶，第二批的多收部分列入「待退」。
5. 在「账户额度 · 认收与待退」面板核对认收、待退与各账户日剩余额度；`GET /api/quota/ledger` 提供累计账本。
6. 下载证据 JSON，核对来源摘要、指标、额度汇总和签发版本。

业务规则见 `docs/BUSINESS-RULES.md`，字段定义见 `docs/DATA-DICTIONARY.md`。

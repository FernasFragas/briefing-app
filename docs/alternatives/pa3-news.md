# PA3 - News Sentiment Alternative

Date researched: 2026-08-31

Scope: research and documentation only. This note does not propose code changes and does not use cached payloads under `data/raw` as entitlement evidence.

> **Implemented 2026-09-01 (ticket I9).** Finnhub was adopted and wired as news primary:
> `news: [finnhub, alpha_vantage, fmp]`. The recommendation below required local sentiment
> scoring and live verification of the entitlement, and both were done — `/news-sentiment`
> is 403 on the free key, exactly as this note predicted, so `providers/news_tone.py`
> derives tone locally and the batch labels it `local tone`. About 50% of live articles
> carry a measurable score. Outcome and limitations:
> `docs/alternatives/pb3-finnhub-news-and-analyst.md`.

## Premise Check

PA3 is needed because the current `S_S` news path has only a throttled primary and a gated fallback:

- `provider-alternatives-wiring-tasks.md` names PA3 as the news sentiment alternative task. It records that Alpha Vantage `NEWS_SENTIMENT` hit the 25 requests/day live limit on 2026-08-31 and that FMP `news/stock` is plan-gated.
- `config/config.example.yaml` configures `providers.news: alpha_vantage`.
- `config/source_registry.yaml` registers Alpha Vantage `news_sentiment` for component `S_S` at `https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={api_key}`.
- `config/source_registry.yaml` registers FMP `stock_news` for component `S_S` at `https://financialmodelingprep.com/stable/news/stock?symbols={ticker}&limit=50&apikey={api_key}`, marked `required: false`, with a note that it is restricted on the current plan.
- `src/briefing_app/pipeline.py` builds the news batch by provider order, trying Alpha Vantage first through `fetch_news_sentiment(...)`, then FMP through `fetch_stock_news(...)`.
- `src/briefing_app/components/sentiment.py` uses scored `NewsArticle.sentiment_score` values in the news summary. Article-only feeds without a sentiment field therefore need a local scoring step before they can be a true `S_S` sentiment input.

The failing/gated providers named in the task are confirmed locally:

- Alpha Vantage `NEWS_SENTIMENT`: current free account is not viable for production `S_S` because Alpha Vantage's support page says the free service is limited to 25 API requests/day.
- FMP `news/stock`: locally marked as restricted on the current plan and named in `docs/SOURCE_STATUS.md` as returning HTTP 402 `Restricted Endpoint`.

Any candidate with Alpha Vantage-equivalent 25 requests/day capacity is a reject, regardless of quality.

## Ranked Verdict

Ranked by requests/day headroom first, then fit/quality.

| Rank | Candidate | Request/day headroom | Sentiment fit | Verdict |
| --- | --- | ---: | --- | --- |
| 1 | Finnhub company/market news | Task cites 60 req/min free; no official daily cap was extractable from the dynamic pricing page in this session. At 60/min steady state, nominal headroom is 86,400/day before any undisclosed plan cap. | Company news is documented as free in Finnhub's public docs text; market news has no premium label in the OpenAPI schema. Finnhub's scored news sentiment endpoint is premium. | Adopt as PA3 article-source winner, with local sentiment scoring and live dashboard verification before wiring. |
| 2 | Tiingo News API | 1,000 req/day and 50 req/hour on Free. | Strong article feed; no sentiment score field in documented response. | Monitor as second fallback or adopt only if Finnhub verification fails. |
| 3 | Benzinga | REST free limit not discoverable. AWS Data Exchange Basic tier claims no usage thresholds, but delivery is not the REST endpoint and sentiment entitlement is unclear. | NewsQuantified has sentiment scores, but free access was not confirmed. | Monitor; do not wire until endpoint entitlement and limits are confirmed with a real key/contract. |
| 4 | RSS feeds / self-hosted SearXNG | No provider API account quota, but effective headroom is source/engine dependent. SearXNG defaults can throttle API requests and upstream engines can suspend on CAPTCHA/429/403. | Headline/source discovery only; no first-party sentiment score. | Reject for PA3 automated scoring; keep as operational fallback/manual headline discovery. |
| Reject | Alpha Vantage free `NEWS_SENTIMENT` | 25 req/day | Direct sentiment feed, but insufficient headroom and currently throttled. | Reject. |

## Candidate Notes

### Finnhub Company/Market News

Base URL and endpoints:

- Base URL: `https://finnhub.io/api/v1`
- Market news: `GET /news?category={general|forex|crypto|merger}&minId={id}&token={api_key}`
- Company news: `GET /company-news?symbol={ticker}&from=YYYY-MM-DD&to=YYYY-MM-DD&token={api_key}`
- News sentiment: `GET /news-sentiment?symbol={ticker}&token={api_key}`

Free-tier limits:

- The PA3 task cites Finnhub company/market news at 60 requests/minute free.
- Finnhub's dynamic pricing page did not expose a machine-readable free-tier row in this browsing session, so this limit must be verified in the dashboard or with a live key before implementation.
- Finnhub's public docs page is dynamic, but its official URL text exposed through current search results confirms rate-limit behavior: exceeded limits return HTTP 429. Finnhub Terms separately state a 30 calls/second limit on top of plan limits.
- Finnhub's public docs URL text exposed through current search results identifies Company News as free tier with 1 year of historical news and new updates. The static OpenAPI schema confirms `/news`, `/company-news`, and `/news-sentiment` endpoint shapes.

Credentials:

- Token in query string: `token={api_key}`
- Or request header: `X-Finnhub-Token: {api_key}`

License/redistribution:

- Finnhub Terms of Service prohibit redistributing, sharing, sublicensing, or providing data or derived results to third parties without written approval.
- The terms also say personal plans are strictly personal.
- This is acceptable for internal brief generation, but not for republishing provider data, full summaries, or derived bulk datasets without approval.

Endpoint stability and anti-bot risk:

- Low anti-bot risk: documented REST API with token auth and JSON responses.
- Main stability risk is entitlement drift: direct scored `/news-sentiment` is premium, so the free path is article retrieval plus local sentiment scoring.

Verdict: adopt as the first PA3 winner, subject to live-key verification of the free rate limit and company-news entitlement. It is not a drop-in replacement for Alpha Vantage scored sentiment; the implementation should add article normalization plus local scoring.

### Tiingo News API

Base URL and endpoints:

- Base URL: `https://api.tiingo.com`
- Latest news: `GET /tiingo/news?tickers={ticker}&limit={n}&token={api_key}`
- Bulk/date news: `GET /tiingo/news?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&tickers={ticker}&token={api_key}`

Free-tier limits:

- Tiingo pricing lists Free at 50 requests/hour and 1,000 requests/day.
- Tiingo News API product page also lists Free at 50/hour and 1,000/day.
- This comfortably clears the 25/day reject threshold, but the hourly cap matters for batch backfills or many-ticker runs.

Credentials:

- Query string token: `token={api_key}`
- Or authorization header, per Tiingo general docs.

License/redistribution:

- Tiingo general documentation says Basic, Power, and Commercial plans cannot redistribute data without explicit permission.
- Pricing defines free/internal use as personal/internal consumption, not public display or sharing.
- Suitable for internal generated briefs; not suitable for republishing raw headlines, descriptions, or provider metadata without permission.

Endpoint stability and anti-bot risk:

- Low anti-bot risk: documented first-party REST API with token auth.
- Endpoint is stable and has structured fields: `title`, `url`, `source`, `publishedDate`, `description`, `tags`, `tickers`, and related metadata.
- Documented response fields do not include a sentiment score, so this also needs local scoring.

Verdict: monitor as the best fallback after Finnhub. It has much less daily headroom than Finnhub's cited 60/min and no native sentiment score, but it is official, documented, and far above Alpha Vantage's 25/day ceiling.

### Benzinga

Base URL and endpoints:

- REST News API: `GET https://api.benzinga.com/api/v2/news`
- REST News API parameters include `pageSize` up to 100, `tickers`, `updatedSince`, `publishedSince`, `channels`, and `topics`.
- NewsQuantified API: `GET https://api.benzinga.com/api/v2/newsquantified`
- NewsQuantified parameters include `pagesize` up to 1,000, `symbols`, and `updated_since`.
- AWS Data Exchange listing: Benzinga Basic News API free tier is delivered as S3 objects through AWS Data Exchange, not the normal REST API shape.

Free-tier limits:

- A usable free REST limit was not discoverable from official Benzinga REST docs.
- Benzinga REST docs document HTTP 403 for permission problems and HTTP 429 for rate limits, but do not publish the free request budget on the pages reviewed.
- The AWS Marketplace listing says the Basic News API free tier has no usage thresholds and zero subscription cost, but it is an AWS Data Exchange/S3 dataset and describes only headline/body teaser/link style data.

Credentials:

- Benzinga REST API key can be sent as `token={api_key}` or via documented headers.
- AWS free tier requires AWS Marketplace/Data Exchange subscription and S3 delivery.

License/redistribution:

- REST API license/redistribution depends on Benzinga contract entitlements.
- AWS Marketplace usage is governed by the marketplace product terms/EULA. The listing distinguishes free headline/teaser/link data from premium full-content offerings.
- Treat redistribution as not allowed unless Benzinga terms explicitly grant it for the chosen plan.

Endpoint stability and anti-bot risk:

- REST API anti-bot risk is low, but entitlement risk is high without a confirmed key.
- The NewsQuantified endpoint is the best semantic match because its documented response is quantified news analytics with sentiment scores and metrics.
- The AWS Basic product may be stable, but its delivery model does not match the existing provider fetch pattern and does not confirm scored sentiment.

Verdict: monitor, not adopt. Benzinga may be the best true sentiment-quality source if NewsQuantified is available on a free or acceptable plan, but the free-tier REST limit and entitlement were not discoverable enough to wire.

### RSS Feeds and SearXNG-Style Options

Base URL and endpoint shapes:

- SearXNG local shape: `GET http://searxng:8080/search?q={query}&categories=news&format=json`
- SearXNG can expose `format=rss` when RSS is enabled in `search.formats`.
- Local repo config currently enables `html` and `json` in `searxng-settings.yml`, not RSS.
- Direct RSS examples:
  - PR Newswire RSS category feeds under `https://www.prnewswire.com/rss/`
  - Nasdaq investor-relations RSS under `https://ir.nasdaq.com/tools/rss-feeds`
  - Publisher/search RSS feeds can be queried by ticker/company keywords where allowed by each site.

Free-tier limits:

- Direct RSS has no API key and no published common daily request limit, but each publisher can throttle or change feeds.
- SearXNG has no external paid quota when self-hosted, but upstream engines impose practical limits. SearXNG's own bot-detection defaults include API request caps, and settings include suspension periods for access denied, CAPTCHA, and too-many-requests errors.
- Public SearXNG instances are not appropriate for scheduled production scraping because API formats may be disabled and public instances may rate-limit.

Credentials:

- None for public RSS feeds.
- None for local SearXNG unless the deployment adds auth or network restrictions.

License/redistribution:

- Source-specific. RSS is generally safe for internal headline/link discovery, but not for republishing full text, bulk content, or derived datasets without checking each publisher's terms.
- PR Newswire and Nasdaq provide RSS feeds, but that does not grant broad rights to redistribute full article content.

Endpoint stability and anti-bot risk:

- Direct RSS stability is medium: feeds are simple and cacheable, but publishers can remove/change categories and item metadata.
- SearXNG anti-bot risk is high for automated financial monitoring because upstream engines can return CAPTCHA, 403, or 429 and SearXNG can temporarily suspend failing engines.
- Results are not guaranteed to be complete, reproducible, or ticker-clean.

Verdict: reject as PA3 automated sentiment source. Keep as a last-resort discovery path or human-readable fallback, not as a scored `S_S` provider. It lacks provider sentiment scores and has higher operational risk than official APIs.

## Recommendation

Adopt Finnhub company news as PA3's primary alternative only if the implementation includes local sentiment scoring and a preflight check verifies the free entitlement/rate limit with the actual key. That gives the most request/day headroom and a documented official API path.

Keep Tiingo as the next fallback candidate because its free limits are explicit and well above 25/day, but its 50/hour cap and lack of sentiment score make it less attractive for the first PA3 integration.

Do not implement Benzinga until a free REST key or contract confirms NewsQuantified access and the request budget. Do not implement RSS/SearXNG as the automated `S_S` source; use it only for optional headline discovery.

## Sources Used

Local sources:

- `provider-alternatives-wiring-tasks.md`
- `docs/SOURCE_STATUS.md`
- `config/config.example.yaml`
- `config/source_registry.yaml`
- `searxng-settings.yml`
- `docker-compose.yml`
- `src/briefing_app/pipeline.py`
- `src/briefing_app/components/sentiment.py`
- `src/briefing_app/providers/alpha_vantage.py`
- `src/briefing_app/providers/fmp.py`
- `src/briefing_app/providers/normalizers.py`

Current internet sources:

- Alpha Vantage Support: `https://www.alphavantage.co/support/`
- Alpha Vantage Documentation, `NEWS_SENTIMENT`: `https://www.alphavantage.co/documentation/`
- Finnhub API docs, dynamic page: `https://finnhub.io/docs/api/quote`
- Finnhub OpenAPI schema: `https://raw.githubusercontent.com/Finnhub-Stock-API/finnhub-go/master/api/openapi.yaml`
- Finnhub Terms of Service: `https://finnhub.io/terms-of-service`
- Finnhub Pricing page checked but not machine-readable in this session: `https://finnhub.io/pricing/`
- Tiingo News API product page: `https://www.tiingo.com/products/news-api`
- Tiingo General API Documentation: `https://www.tiingo.com/documentation/general`
- Tiingo News API Documentation: `https://www.tiingo.com/documentation/news`
- Tiingo Pricing: `https://www.tiingo.com/about/pricing`
- Benzinga Authentication docs: `https://docs.benzinga.com/api-reference/authentication`
- Benzinga News API docs: `https://docs.benzinga.com/api-reference/news-api/get-news-items`
- Benzinga NewsQuantified docs: `https://docs.benzinga.com/api-reference/newsquantified-api/get-newsquantified-data`
- Benzinga Error docs: `https://docs.benzinga.com/api-reference/errors`
- Benzinga AWS Marketplace Basic News API free tier listing: `https://aws.amazon.com/marketplace/pp/prodview-xwgvhwowjmw3g`
- SearXNG Search API docs: `https://github.com/searxng/searxng/blob/master/docs/dev/search_api.rst`
- SearXNG user/admin docs: `https://docs.searxng.org/index.html`
- SearXNG search settings docs: `https://docs.searxng.org/admin/settings/settings_search.html`
- SearXNG bot detection docs: `https://docs.searxng.org/src/searx.botdetection.html`
- PR Newswire RSS page: `https://www.prnewswire.com/rss/`
- Nasdaq, Inc. RSS feeds page: `https://ir.nasdaq.com/tools/rss-feeds`

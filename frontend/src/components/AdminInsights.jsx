import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowDownRight, ArrowUpRight, Code2, Download, Minus } from 'lucide-react';
import NeoButton from './NeoButton';
import { Card, Chip, ErrorBox, Input, Modal, Spinner, UserLink } from './ui';
import { admin, errorMessage } from '../services/api';

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------
const NoData = () => <p className="label text-text-muted py-8 text-center">No data in this period</p>;

const RANGES = [
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
  { id: '90d', label: '90 days' },
  { id: '12m', label: '12 months' },
  { id: 'ytd', label: 'This year' },
  { id: 'last_year', label: 'Last year' },
  { id: 'all', label: 'All time' },
];

const fmt = (n) => (n === null || n === undefined ? '–' : Number(n).toLocaleString());
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const parseDay = (iso) => { const [y, m, d] = iso.split('-').map(Number); return { y, m, d }; };
const periodLabel = (iso, bucket, long = false) => {
  const { y, m, d } = parseDay(iso);
  if (bucket === 'month') return long ? `${MONTHS[m - 1]} ${y}` : `${MONTHS[m - 1]} ’${String(y).slice(2)}`;
  if (bucket === 'week') return long ? `Week of ${d} ${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]}`;
  return long ? `${d} ${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]}`;
};
const niceDate = (iso) => periodLabel(iso, 'day', true);

const toCsv = (rows) => {
  if (!rows?.length) return '';
  const cols = Object.keys(rows[0]);
  const cell = (v) => {
    const s = v === null || v === undefined ? '' : Array.isArray(v) ? v.join('; ') : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(','), ...rows.map((r) => cols.map((c) => cell(r[c])).join(','))].join('\n');
};
const downloadCsv = (name, rows) => {
  const blob = new Blob([toCsv(Array.isArray(rows) ? rows : [rows])], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
};

// SQL with keywords picked out, so it reads well in the modal
const SQL_WORDS = 'WITH|SELECT|FROM|LEFT JOIN|JOIN|USING|ON|WHERE|AND|OR|NOT|GROUP BY|HAVING|ORDER BY|LIMIT|AS|CASE|WHEN|THEN|ELSE|END|FILTER|OVER|UNION ALL|DISTINCT|BETWEEN|IS|NULL|DESC|ASC|DENSE_RANK|RANK|COALESCE|NULLIF|EXTRACT|LEAST|generate_series|date_trunc|make_date|count|sum|avg|min|max|round|ARRAY';
const SQL_SPLIT = new RegExp(`\\b(${SQL_WORDS})\\b`);
const SQL_WORD = new RegExp(`^(${SQL_WORDS})$`);
const SqlBlock = ({ sql }) => (
  <pre className="bg-surface-white rounded-[20px] p-4 text-[12.5px] leading-[1.55] overflow-x-auto whitespace-pre font-mono text-text-main" data-lenis-prevent>
    {sql.split(SQL_SPLIT).map((p, i) => (i % 2 && SQL_WORD.test(p) ? <b key={i} className="text-red-deep">{p}</b> : <span key={i}>{p}</span>))}
  </pre>
);

// ---------------------------------------------------------------------
// Charts (one series each: a single hue, with hover detail and a table view)
// ---------------------------------------------------------------------
const ColumnChart = ({ rows, x, y, label, height = 220, tooltip }) => {
  const [hover, setHover] = useState(null);
  if (!rows.length) return <NoData />;
  const max = Math.max(1, ...rows.map((r) => Number(r[y]) || 0));
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const top = Math.ceil(max / step) * step;
  const ticks = [0, top / 2, top];
  const W = 1000, H = height, padL = 40, padB = 28, padT = 10;
  const bw = (W - padL) / rows.length;
  const gap = Math.min(6, bw * 0.25);
  const every = Math.ceil(rows.length / 12);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label={label}>
        {ticks.map((t) => {
          const ty = padT + (H - padT - padB) * (1 - t / top);
          return (
            <g key={t}>
              <line x1={padL} x2={W} y1={ty} y2={ty} stroke="var(--color-border)" strokeWidth="1" />
              <text x={padL - 8} y={ty + 4} textAnchor="end" fontSize="12" fill="var(--color-text-muted)">{fmt(t)}</text>
            </g>
          );
        })}
        {rows.map((r, i) => {
          const v = Number(r[y]) || 0;
          const h = ((H - padT - padB) * v) / top;
          const bx = padL + i * bw + gap / 2;
          const by = H - padB - h;
          const on = hover === i;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={padL + i * bw} y={padT} width={bw} height={H - padT - padB} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${bx},${H - padB} V${by + Math.min(4, h)} Q${bx},${by} ${bx + Math.min(4, (bw - gap) / 2)},${by} H${bx + bw - gap - Math.min(4, (bw - gap) / 2)} Q${bx + bw - gap},${by} ${bx + bw - gap},${by + Math.min(4, h)} V${H - padB} Z`}
                  fill={on ? 'var(--color-red)' : 'var(--color-accent-teal)'}
                />
              )}
              {i % every === 0 && (
                <text x={bx + (bw - gap) / 2} y={H - 8} textAnchor="middle" fontSize="12" fill="var(--color-text-muted)">{r[x]}</text>
              )}
            </g>
          );
        })}
        <line x1={padL} x2={W} y1={H - padB} y2={H - padB} stroke="var(--color-text-main)" strokeOpacity="0.4" />
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-[14px] bg-text-main text-bg-base px-3 py-2 text-[12px] whitespace-nowrap shadow-brutal-lg"
          style={{ left: `${((padL + (hover + 0.5) * bw) / W) * 100}%` }}
        >
          {tooltip(rows[hover])}
        </div>
      )}
    </div>
  );
};

const BarList = ({ rows, label, value, suffix, max: maxProp, detail }) => {
  if (!rows.length) return <NoData />;
  const max = maxProp ?? Math.max(1, ...rows.map((r) => Number(r[value]) || 0));
  return (
    <ul className="space-y-2">
      {rows.map((r, i) => (
        <li key={i} className="grid grid-cols-[minmax(0,10rem)_1fr_auto] items-center gap-3 group" title={detail ? detail(r) : undefined}>
          <span className="font-medium truncate text-[14px]">{label(r)}</span>
          <span className="h-3 rounded-full bg-bg-base overflow-hidden">
            <span
              className="block h-full rounded-full bg-accent-teal group-hover:bg-red transition-colors"
              style={{ width: `${Math.max(2, (100 * (Number(r[value]) || 0)) / max)}%` }}
            />
          </span>
          <span className="label text-right min-w-[4.5rem] tabular-nums">{fmt(r[value])}{suffix ? ` ${suffix}` : ''}</span>
        </li>
      ))}
    </ul>
  );
};

const DataTable = ({ cols, rows, render }) => (
  rows.length ? (
    <div className="overflow-x-auto rounded-[20px] border border-border bg-surface-white">
      <table className="w-full text-left text-[14px]">
        <thead className="bg-text-main text-bg-base">
          <tr>{cols.map((c) => <th key={c} className="px-3 py-2 font-medium whitespace-nowrap">{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border hover:bg-bg-base">{render(r).map((cell, j) => <td key={j} className="px-3 py-2 tabular-nums">{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : <NoData />
);

// ---------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------
const Panel = ({ section, name, children, className, onSql }) => (
  <Card className={className}>
    <div className="flex items-start justify-between gap-3 mb-1">
      <h3 className="font-display text-[clamp(1.5rem,2.2vw,2rem)] leading-none">{section.title}</h3>
      <div className="flex gap-1.5 shrink-0">
        <button onClick={() => onSql(name)} className="h-8 px-3 rounded-full border-[1.5px] border-red/40 hover:border-red text-[12px] flex items-center gap-1" aria-label={`SQL for ${section.title}`}>
          <Code2 className="w-3.5 h-3.5" /> SQL
        </button>
        <button onClick={() => downloadCsv(name, section.rows)} className="h-8 px-3 rounded-full border-[1.5px] border-red/40 hover:border-red text-[12px] flex items-center gap-1" aria-label={`Download ${section.title} as CSV`}>
          <Download className="w-3.5 h-3.5" /> CSV
        </button>
      </div>
    </div>
    <p className="text-[13px] text-text-muted mb-5 max-w-prose">{section.about}</p>
    {children}
  </Card>
);

const Delta = ({ now, prev, absolute }) => {
  if (prev === null || prev === undefined || Number(prev) === 0 || now === null || now === undefined) {
    return <span className="label text-text-muted">no earlier data</span>;
  }
  const diff = Number(now) - Number(prev);
  const text = absolute ? `${diff >= 0 ? '+' : ''}${diff.toFixed(2)}` : `${diff >= 0 ? '+' : ''}${Math.round((100 * diff) / Number(prev))}%`;
  const Icon = diff > 0 ? ArrowUpRight : diff < 0 ? ArrowDownRight : Minus;
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-medium">
      <Icon className="w-3.5 h-3.5" aria-hidden />
      {text} <span className="text-text-muted font-normal">vs previous</span>
    </span>
  );
};

const KPIS = [
  ['books_logged', 'Books logged'],
  ['active_readers', 'Active readers'],
  ['unique_books', 'Different books'],
  ['pages_read', 'Pages read'],
  ['avg_rating', 'Average rating', true],
  ['reviews', 'Reviews written'],
  ['new_readers', 'New readers'],
];

const METRICS = [
  { id: 'books_logged', label: 'Books logged' },
  { id: 'readers', label: 'Active readers' },
  { id: 'reviews', label: 'Reviews' },
  { id: 'new_readers', label: 'New readers' },
];

const GLOSSARY = [
  ['Aggregates + GROUP BY', 'count, sum, avg, min, max per book, genre, author or reader.'],
  ['FILTER (WHERE …)', 'Several conditional counts from one scan: this period vs the previous one, likes, shelf types.'],
  ['Window functions', 'DENSE_RANK() / RANK() OVER (ORDER BY …) for leaderboards; sum(count(*)) OVER () for percentage shares.'],
  ['CTE (WITH …)', 'Names an intermediate result (the timeline buckets, per-genre counts) so the final query stays readable.'],
  ['generate_series', 'Builds every day/week/month, every half-star rating and every weekday, so gaps show as 0.'],
  ['LEFT JOIN', 'Keeps rows with no matches (empty months, readers with no followers).'],
  ['date_trunc / EXTRACT', 'Groups dates into days, weeks, months; ISODOW gives the weekday.'],
  ['HAVING', 'Filters groups after aggregation, e.g. books with at least 2 ratings.'],
  ['CASE', 'Buckets values into labels: book length, publication era, goal status.'],
  ['Scalar subqueries + UNION ALL', 'The engagement funnel: one number per step, stacked into rows.'],
  ['Many-to-many joins', 'book_author and book_genre bridge tables connect books to authors and genres.'],
  ['Row-level security', 'diary_entry has RLS; the admin session (app.role = admin) may read private diaries, readers may not.'],
];

// ---------------------------------------------------------------------
// Page section
// ---------------------------------------------------------------------
const AdminInsights = () => {
  const [range, setRange] = useState('30d');
  const [custom, setCustom] = useState({ start: '', end: '' });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [metric, setMetric] = useState('books_logged');
  const [sqlFor, setSqlFor] = useState(null); // section key, or 'all'

  const load = useCallback((params) => {
    setError(null);
    admin.insights(params).then(setData).catch((e) => setError(errorMessage(e)));
  }, []);

  useEffect(() => {
    if (range !== 'custom') load({ range });
  }, [range, load]);

  const applyCustom = () => {
    if (custom.start && custom.end) load({ range: 'custom', start: custom.start, end: custom.end });
  };

  const s = data?.sections;
  const meta = data?.range;
  const timeline = useMemo(
    () => (s ? s.timeline.rows.map((r) => ({ ...r, label: periodLabel(r.period, meta.bucket) })) : []),
    [s, meta],
  );

  if (error) return <ErrorBox>{error}</ErrorBox>;

  return (
    <div className="space-y-8">
      {/* Time frame */}
      <Card className="!p-5">
        <div className="flex flex-wrap items-center gap-2">
          {RANGES.map((r) => <Chip key={r.id} active={range === r.id} onClick={() => setRange(r.id)}>{r.label}</Chip>)}
          <Chip active={range === 'custom'} onClick={() => setRange('custom')}>Custom</Chip>
          <span className="flex-1" />
          <NeoButton size="sm" variant="white" onClick={() => setSqlFor('all')}><Code2 className="w-4 h-4 mr-1" /> How these are computed</NeoButton>
        </div>
        {range === 'custom' && (
          <div className="flex flex-wrap items-end gap-3 mt-4">
            <label className="text-[12px] caps">From<Input type="date" value={custom.start} onChange={(e) => setCustom({ ...custom, start: e.target.value })} className="mt-1" /></label>
            <label className="text-[12px] caps">To<Input type="date" value={custom.end} onChange={(e) => setCustom({ ...custom, end: e.target.value })} className="mt-1" /></label>
            <NeoButton size="sm" variant="primary" onClick={applyCustom} disabled={!custom.start || !custom.end}>Apply</NeoButton>
          </div>
        )}
        {meta && (
          <p className="text-[13px] text-text-muted mt-3">
            Showing {niceDate(meta.start)} to {niceDate(meta.end)} ({meta.days} days), compared with {niceDate(meta.prev_start)} to {niceDate(meta.prev_end)}.
          </p>
        )}
      </Card>

      {!data ? <Spinner label="Crunching the numbers" /> : (
        <>
          {/* Headline numbers */}
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
            {KPIS.map(([key, label, absolute]) => (
              <Card key={key} className="!p-4">
                <div className="font-display text-[clamp(1.8rem,2.6vw,2.6rem)] leading-none tabular-nums">
                  {key === 'avg_rating' ? (s.kpis.rows[key] ?? '–') : fmt(s.kpis.rows[key])}
                </div>
                <div className="caps mt-1 mb-2">{label}</div>
                <Delta now={s.kpis.rows[key]} prev={s.kpis.rows[`${key}_prev`]} absolute={absolute} />
              </Card>
            ))}
          </div>
          <div className="flex justify-end -mt-5 gap-2">
            <button onClick={() => setSqlFor('kpis')} className="label link-under">SQL for these numbers</button>
          </div>

          {/* Timeline */}
          <Panel section={s.timeline} name="timeline" onSql={setSqlFor}>
            <div className="flex flex-wrap gap-2 mb-4">
              {METRICS.map((m) => <Chip key={m.id} active={metric === m.id} onClick={() => setMetric(m.id)} className="!h-9 !text-[15px]">{m.label}</Chip>)}
            </div>
            <ColumnChart
              rows={timeline}
              x="label"
              y={metric}
              label={`${METRICS.find((m) => m.id === metric).label} per ${meta.bucket}`}
              tooltip={(r) => (
                <>
                  <b className="block mb-0.5">{periodLabel(r.period, meta.bucket, true)}</b>
                  {METRICS.map((m) => <span key={m.id} className="block">{m.label}: {fmt(r[m.id])}</span>)}
                </>
              )}
            />
          </Panel>

          {/* Books */}
          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.most_read} name="most_read" onSql={setSqlFor}>
              <DataTable cols={['#', 'Book', 'Readers', 'Logs', 'Avg ★', 'Likes']} rows={s.most_read.rows} render={(r) => [
                r.rank,
                <span><Link to={`/book/${encodeURIComponent(r.title)}`} className="font-medium hover:underline">{r.title}</Link><span className="block text-[12px] text-text-muted">{r.author}</span></span>,
                r.readers, r.logs, r.avg_rating ?? '–', r.likes,
              ]} />
            </Panel>
            <Panel section={s.top_rated} name="top_rated" onSql={setSqlFor}>
              <DataTable cols={['Book', 'Ratings', 'Avg ★', 'Range']} rows={s.top_rated.rows} render={(r) => [
                <span><Link to={`/book/${encodeURIComponent(r.title)}`} className="font-medium hover:underline">{r.title}</Link><span className="block text-[12px] text-text-muted">{r.author}</span></span>,
                r.ratings, r.avg_rating, `${r.lowest}–${r.highest}`,
              ]} />
            </Panel>
          </div>

          {/* Genres and authors */}
          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.genres} name="genres" onSql={setSqlFor}>
              <BarList rows={s.genres.rows} label={(r) => r.genre} value="logs" suffix="logs"
                detail={(r) => `${r.genre}: ${r.logs} logs, ${r.share_pct}% of all, ${r.readers} readers, avg ${r.avg_rating ?? '–'}★`} />
              <p className="label text-text-muted mt-3">Hover a bar for share and rating.</p>
            </Panel>
            <Panel section={s.genre_momentum} name="genre_momentum" onSql={setSqlFor}>
              <DataTable cols={['Genre', 'This period', 'Before', 'Change']} rows={s.genre_momentum.rows} render={(r) => [
                <span className="font-medium">{r.genre}</span>, r.this_period, r.previous_period,
                r.change_pct === null ? <span className="label">new</span> : `${r.change_pct > 0 ? '+' : ''}${r.change_pct}%`,
              ]} />
            </Panel>
          </div>

          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.authors} name="authors" onSql={setSqlFor}>
              <BarList rows={s.authors.rows} label={(r) => r.author} value="logs" suffix="logs"
                detail={(r) => `${r.author}: ${r.books} books, ${r.readers} readers, avg ${r.avg_rating ?? '–'}★`} />
            </Panel>
            <Panel section={s.readers} name="readers" onSql={setSqlFor}>
              <DataTable cols={['#', 'Reader', 'Books', 'Pages', 'Reviews', 'Re-reads', 'Avg ★']} rows={s.readers.rows} render={(r) => [
                r.rank, <UserLink username={r.username} />, r.books_logged, fmt(r.pages), r.reviews, r.rereads, r.avg_rating ?? '–',
              ]} />
            </Panel>
          </div>

          {/* Distributions */}
          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.ratings} name="ratings" onSql={setSqlFor}>
              <ColumnChart rows={s.ratings.rows.map((r) => ({ ...r, label: `${r.rating}★` }))} x="label" y="entries" height={200}
                label="Number of entries per star rating" tooltip={(r) => <><b>{r.rating} stars</b><span className="block">{fmt(r.entries)} entries</span></>} />
            </Panel>
            <Panel section={s.weekday} name="weekday" onSql={setSqlFor}>
              <ColumnChart rows={s.weekday.rows} x="day" y="books_logged" height={200}
                label="Books logged per weekday" tooltip={(r) => <><b>{r.day}</b><span className="block">{fmt(r.books_logged)} books</span></>} />
            </Panel>
          </div>

          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.eras} name="eras" onSql={setSqlFor}>
              <BarList rows={s.eras.rows} label={(r) => r.era} value="books_logged" detail={(r) => `${r.era}: ${r.books_logged} books, avg ${r.avg_rating ?? '–'}★`} />
            </Panel>
            <Panel section={s.lengths} name="lengths" onSql={setSqlFor}>
              <BarList rows={s.lengths.rows} label={(r) => r.length} value="books_logged" detail={(r) => `${r.length}: avg ${r.avg_rating ?? '–'}★`} />
            </Panel>
          </div>

          {/* Community */}
          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.funnel} name="funnel" onSql={setSqlFor}>
              <BarList rows={s.funnel.rows} label={(r) => r.stage} value="readers" suffix="readers" max={s.funnel.rows[0]?.readers || 1}
                detail={(r) => `${r.stage}: ${Math.round((100 * r.readers) / (s.funnel.rows[0]?.readers || 1))}% of sign-ups`} />
            </Panel>
            <Panel section={s.goals} name="goals" onSql={setSqlFor}>
              <DataTable cols={['Reader', 'Goal', 'Done', 'Progress', 'Status']} rows={s.goals.rows} render={(r) => [
                <UserLink username={r.username} />, r.target_books, r.books_finished,
                <span className="flex items-center gap-2 min-w-[7rem]">
                  <span className="h-2 flex-1 rounded-full bg-bg-base overflow-hidden"><span className="block h-full bg-accent-teal" style={{ width: `${Math.min(100, r.pct)}%` }} /></span>
                  <span className="text-[12px] w-10 text-right">{r.pct}%</span>
                </span>,
                <span className="caps text-[12px]">{r.status}</span>,
              ]} />
            </Panel>
          </div>

          <div className="grid xl:grid-cols-2 gap-6">
            <Panel section={s.shelves} name="shelves" onSql={setSqlFor}>
              <DataTable cols={['Book', 'Want to read', 'Reading now']} rows={s.shelves.rows} render={(r) => [
                <Link to={`/book/${encodeURIComponent(r.title)}`} className="font-medium hover:underline">{r.title}</Link>, r.want_to_read, r.reading_now,
              ]} />
            </Panel>
            <Panel section={s.social} name="social" onSql={setSqlFor}>
              <DataTable cols={['Reader', 'Followers', 'Following', 'Lists']} rows={s.social.rows} render={(r) => [
                <UserLink username={r.username} />, r.followers, r.following, r.lists,
              ]} />
            </Panel>
          </div>
        </>
      )}

      {/* SQL explainer */}
      <Modal open={!!sqlFor && !!data} onClose={() => setSqlFor(null)} wide
        title={sqlFor === 'all' ? 'How these analytics are computed' : s?.[sqlFor]?.title || 'SQL'}>
        {data && sqlFor === 'all' && (
          <>
            <p className="text-[14px] mb-4">
              Every number on this page comes from one SQL query on the PostgreSQL database, run live when you pick a time frame.
              Named parameters are filled in by the API:
            </p>
            <div className="grid sm:grid-cols-2 gap-2 mb-6 text-[13px]">
              {[['start', meta.start], ['end', meta.end], ['prev_start', meta.prev_start], ['prev_end', meta.prev_end], ['bucket', meta.bucket], ['year', meta.year]].map(([k, v]) => (
                <div key={k} className="rounded-[14px] bg-surface-white px-3 py-2"><code className="text-red-deep">:{k}</code> = {String(v)}</div>
              ))}
            </div>
            <h4 className="font-display text-[1.6rem] mb-3">SQL features used</h4>
            <dl className="grid sm:grid-cols-2 gap-3 mb-8">
              {GLOSSARY.map(([term, desc]) => (
                <div key={term} className="rounded-[18px] bg-surface-white p-4">
                  <dt className="font-medium mb-1">{term}</dt>
                  <dd className="text-[13px] text-text-muted">{desc}</dd>
                </div>
              ))}
            </dl>
            <h4 className="font-display text-[1.6rem] mb-3">Every query</h4>
            <div className="space-y-6">
              {Object.entries(s).map(([key, sec]) => (
                <section key={key}>
                  <p className="font-medium">{sec.title}</p>
                  <p className="text-[13px] text-text-muted mb-2">{sec.about}</p>
                  <SqlBlock sql={sec.sql} />
                </section>
              ))}
            </div>
          </>
        )}
        {data && sqlFor && sqlFor !== 'all' && s[sqlFor] && (
          <>
            <p className="text-[14px] mb-4">{s[sqlFor].about}</p>
            <SqlBlock sql={s[sqlFor].sql} />
            <p className="text-[12px] text-text-muted mt-3">
              Ran with :start = {meta.start}, :end = {meta.end}{sqlFor === 'kpis' || sqlFor === 'genre_momentum' ? `, :prev_start = ${meta.prev_start}, :prev_end = ${meta.prev_end}` : ''}{sqlFor === 'timeline' ? `, :bucket = '${meta.bucket}'` : ''}{sqlFor === 'goals' ? `, :year = ${meta.year}` : ''}.
            </p>
          </>
        )}
      </Modal>
    </div>
  );
};

export default AdminInsights;

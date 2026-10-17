import React, { useEffect, useState, useCallback } from 'react'
import { md } from './markdown.js'

const api = {
  async get(path) { const r = await fetch(path); return r.json() },
  async post(path, body) {
    const r = await fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    return r.json()
  },
}

const LABEL_COLOR = { private: '#b4304a', public: '#1f7a4d', mixed: '#9a6a00', service: '#555' }

function LabelBadge({ label }) {
  return <span className="badge" style={{ background: LABEL_COLOR[label] || '#555' }}>{label}</span>
}

function Summary({ summary }) {
  if (!summary) return null
  if (!summary.ok) return <div className="summary err">⚠ {summary.error}</div>
  const c = summary.counts
  return (
    <div className="summary ok">
      <div className="counts">
        <b>{summary.name}</b> · {c.servers} servers ({c.http} http, {c.stdio} stdio) ·
        {' '}{c.clients} clients · {c.domains} domains · {c.services} services ·
        {' '}gateway <code>{summary.gateway}</code> · seed {summary.seed}
      </div>
      {summary.warnings?.length > 0 && (
        <ul className="warnings">{summary.warnings.map((w, i) => <li key={i}>warning: {w}</li>)}</ul>
      )}
      <table className="servers">
        <thead><tr><th>server</th><th>transport</th><th>label</th><th>domain</th><th>runtime</th></tr></thead>
        <tbody>
          {summary.servers.map((s) => (
            <tr key={s.id}>
              <td><code>{s.id}</code></td><td>{s.transport}</td>
              <td><LabelBadge label={s.label} /></td><td>{s.domain || '—'}</td><td>{s.runtime}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function App() {
  const [info, setInfo] = useState(null)
  const [testbeds, setTestbeds] = useState([])
  const [name, setName] = useState('')
  const [yaml, setYaml] = useState('')
  const [summary, setSummary] = useState(null)
  const [output, setOutput] = useState('')
  const [busy, setBusy] = useState('')
  const [tab, setTab] = useState('configure')
  const [catalogue, setCatalogue] = useState('')

  const refreshList = useCallback(async () => setTestbeds(await api.get('/api/testbeds')), [])

  useEffect(() => {
    api.get('/api/info').then(setInfo)
    refreshList()
    api.get('/api/catalogue').then((d) => setCatalogue(d.markdown || ''))
  }, [refreshList])

  async function load(n) {
    const d = await api.get('/api/testbed?name=' + encodeURIComponent(n))
    setName(n); setYaml(d.yaml || ''); setSummary(d.summary); setOutput('')
  }

  function newTestbed() {
    setName('my-testbed'); setSummary(null); setOutput('')
    setYaml(`testbed: my-testbed
version: 1
seed: 2026

defaults:
  transport: http

domains:
  - id: corp
  - id: public
    internet: true

servers:
  - id: hr
    runtime: local
    path: ../servers/sample-db
    args: ["--db", "/data/hr/company.db"]
    domain: corp
    label: private
  - id: fetch
    runtime: python
    package: mcp-server-fetch
    domain: public
    label: public
    plant_canaries: false

clients:
  - id: agent
    servers: [hr, fetch]
`)
  }

  async function validate() {
    setBusy('validate'); setSummary(await api.post('/api/validate', { yaml })); setBusy('')
  }
  async function save() {
    setBusy('save'); const d = await api.post('/api/save', { name, yaml })
    setSummary(d.summary); await refreshList(); setBusy('')
  }
  async function runAction(action) {
    setBusy(action); setOutput(`$ mcl ${action} ${name}\n…running…`)
    const d = await api.post('/api/action', { name, action })
    setOutput(`$ mcl ${action} ${name}  (exit ${d.returncode})\n\n${d.stdout || ''}${d.stderr ? '\n' + d.stderr : ''}`)
    setBusy('')
  }
  async function status() {
    setBusy('status'); const d = await api.get('/api/status?name=' + encodeURIComponent(name))
    setOutput(d.built ? d.ps : '(not built yet — run Build)'); setBusy('')
  }

  const actions = ['build', 'up', 'smoke', 'reset', 'down']

  return (
    <div className="app">
      <header>
        <h1>MCP CyberNet Lab</h1>
        <span className="sub">
          configure &amp; run containerised MCP testbeds
          {info && <> · v{info.version}</>}
        </span>
        <nav>
          <button className={tab === 'configure' ? 'on' : ''} onClick={() => setTab('configure')}>Configure</button>
          <button className={tab === 'catalogue' ? 'on' : ''} onClick={() => setTab('catalogue')}>Server catalogue</button>
        </nav>
      </header>

      {tab === 'configure' ? (
        <div className="cols">
          <aside>
            <div className="aside-head">
              <span>Testbeds</span>
              <button onClick={newTestbed}>+ New</button>
            </div>
            <ul className="tb-list">
              {testbeds.map((t) => (
                <li key={t.name} className={t.name === name ? 'on' : ''} onClick={() => load(t.name)}>
                  <span>{t.name}</span>
                  {t.summary?.ok
                    ? <small>{t.summary.counts.servers} srv</small>
                    : <small className="bad">invalid</small>}
                </li>
              ))}
              {testbeds.length === 0 && <li className="empty">no testbeds found</li>}
            </ul>
          </aside>

          <main>
            <div className="name-row">
              <label>name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="my-testbed" /></label>
              <button disabled={busy} onClick={validate}>Validate</button>
              <button disabled={busy || !name} onClick={save}>Save</button>
            </div>
            <textarea className="yaml" value={yaml} spellCheck={false}
              onChange={(e) => setYaml(e.target.value)} placeholder="Select a testbed or click + New" />
            <Summary summary={summary} />

            <div className="actions">
              {actions.map((a) => (
                <button key={a} disabled={busy || !name} onClick={() => runAction(a)}
                  className={'act act-' + a}>{busy === a ? '…' : a}</button>
              ))}
              <button disabled={busy || !name} onClick={status}>status</button>
            </div>
            {output && <pre className="console">{output}</pre>}
          </main>
        </div>
      ) : (
        <main className="doc" dangerouslySetInnerHTML={{ __html: md(catalogue || '# Server catalogue\n\nNo catalogue document found in `docs/`.') }} />
      )}
    </div>
  )
}

import { useEffect, useRef, useState } from "react";
import {
  collect,
  genSamples,
  getHealth,
  getSampleEmail,
  type Health,
} from "./api";
import type { CollectResponse } from "./types";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [useGraph, setUseGraph] = useState(true);
  const [useLlm, setUseLlm] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CollectResponse | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  async function loadSampleEmail() {
    const s = await getSampleEmail();
    setSubject(s.subject);
    setBody(s.body);
  }

  async function makeSamples() {
    await genSamples();
    alert("샘플 엑셀 3개를 data/samples 에 생성했습니다. 파일 선택에서 업로드하세요.");
  }

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    setFiles(Array.from(e.target.files ?? []));
  }

  async function run() {
    setError(null);
    if (!subject.trim() || !body.trim()) {
      setError("메일 제목과 본문을 입력하세요.");
      return;
    }
    if (files.length === 0) {
      setError("엑셀 파일을 1개 이상 업로드하세요.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const res = await collect({ subject, body, useGraph, useLlm, files });
      setResult(res);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  const vr = result?.validation_result;

  return (
    <div className="app">
      <header className="header">
        <h1>📊 Smart Collect Assistant</h1>
        <p className="sub">취합 요청 메일 분석 → 엑셀 검증 → 정상 데이터 병합 → 오류 보고서</p>
        {health && (
          <div className="badges">
            <span className="badge">Azure {health.azure_ready ? "ON" : "휴리스틱"}</span>
            <span className="badge">RAG {health.use_rag ? "ON" : "OFF"}</span>
            <span className="badge">Langfuse {health.use_langfuse ? "ON" : "OFF"}</span>
          </div>
        )}
      </header>

      <div className="grid">
        {/* 입력 패널 */}
        <section className="card">
          <h2>1. 취합 요청 메일</h2>
          <div className="row">
            <button className="ghost" onClick={loadSampleEmail}>샘플 메일 불러오기</button>
            <button className="ghost" onClick={makeSamples}>샘플 엑셀 생성</button>
          </div>
          <label>메일 제목</label>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="예: 2026년 6월 시스템 개선 요청사항 취합" />
          <label>메일 본문</label>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={7} placeholder="작성 항목, 마감일, 긴급도 기준 등을 포함한 본문" />

          <h2>2. 제출 엑셀 업로드</h2>
          <input ref={fileInput} type="file" accept=".xlsx,.xls" multiple onChange={onPick} />
          {files.length > 0 && (
            <ul className="filelist">
              {files.map((f) => (
                <li key={f.name}>📄 {f.name}</li>
              ))}
            </ul>
          )}

          <h2>3. 실행 옵션</h2>
          <label className="check">
            <input type="checkbox" checked={useGraph} onChange={(e) => setUseGraph(e.target.checked)} />
            LangGraph 멀티에이전트 워크플로우 사용
          </label>
          <label className="check">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            메일 분석에 LLM 사용 (키 없으면 자동 휴리스틱)
          </label>

          <button className="primary" onClick={run} disabled={loading}>
            {loading ? "처리 중…" : "검증 · 병합 실행"}
          </button>
          {error && <p className="error">⚠ {error}</p>}
        </section>

        {/* 결과 패널 */}
        <section className="card">
          <h2>결과</h2>
          {!result && <p className="muted">왼쪽에서 메일과 엑셀을 입력하고 실행하세요.</p>}

          {result && vr && (
            <>
              <div className="stats">
                <Stat label="파일" value={vr.total_files} />
                <Stat label="전체 행" value={vr.total_rows} />
                <Stat label="정상" value={vr.valid_rows} tone="ok" />
                <Stat label="오류" value={vr.error_rows} tone={vr.error_rows ? "bad" : "ok"} />
              </div>

              {result.extracted_requirements && (
                <div className="block">
                  <h3>메일 분석</h3>
                  <p><b>제출 기한:</b> {result.extracted_requirements.deadline ?? "확인 필요"}</p>
                  <div className="chips">
                    {result.extracted_requirements.required_fields.map((f) => (
                      <span className="chip" key={f}>{f}</span>
                    ))}
                  </div>
                </div>
              )}

              {result.validation_rules && (
                <div className="block">
                  <h3>적용된 검증 규칙</h3>
                  <p><b>필수:</b> {result.validation_rules.required_columns.join(", ") || "-"}</p>
                  <p><b>날짜:</b> {result.validation_rules.date_columns.join(", ") || "-"}</p>
                  <p><b>코드값:</b> {Object.entries(result.validation_rules.code_rules).map(([k, v]) => `${k}=${v.join("/")}`).join(", ") || "-"}</p>
                  <p><b>중복키:</b> {result.validation_rules.duplicate_keys.join(", ") || "-"}</p>
                </div>
              )}

              {vr.error_details.length > 0 && (
                <div className="block">
                  <h3>오류 상세 ({vr.error_details.length})</h3>
                  <table className="errtable">
                    <thead>
                      <tr><th>파일</th><th>행</th><th>컬럼</th><th>유형</th><th>입력값</th></tr>
                    </thead>
                    <tbody>
                      {vr.error_details.map((e, i) => (
                        <tr key={i}>
                          <td>{e.file}</td>
                          <td>{e.row}</td>
                          <td>{e.column}</td>
                          <td><span className="etype">{e.error_type}</span></td>
                          <td>{e.value ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="block downloads">
                {result.downloads.merged && (
                  <a className="primary" href={result.downloads.merged}>⬇ 병합 파일</a>
                )}
                {result.downloads.error && (
                  <a className="ghost" href={result.downloads.error}>⬇ 오류 보고서</a>
                )}
              </div>

              <div className="block">
                <h3>에이전트 실행 흐름</h3>
                <div className="flow">
                  {result.agent_handoff_history.map((h, i) => (
                    <span className="node" key={i}>{h.split(":")[1] ?? h}</span>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "ok" | "bad" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="num">{value}</div>
      <div className="lbl">{label}</div>
    </div>
  );
}

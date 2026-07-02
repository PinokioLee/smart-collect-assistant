import { useEffect, useRef, useState } from "react";
import {
  collect,
  createGuide,
  genSamples,
  getHealth,
  getSampleEmail,
  getStyleMails,
  saveStyleMail,
  uploadStyleMails,
  sendEmail,
  trackSubmissions,
  updateFields,
  type GuideResponse,
  type Health,
  type SendEmailResponse,
  type TrackResponse,
  type UpdateFieldsResponse,
} from "./api";
import type { CollectResponse } from "./types";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [guideLoading, setGuideLoading] = useState(false);
  const [sendLoading, setSendLoading] = useState(false);
  const [trackLoading, setTrackLoading] = useState(false);
  const [updateLoading, setUpdateLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CollectResponse | null>(null);
  const [guide, setGuide] = useState<GuideResponse | null>(null);
  const [recipients, setRecipients] = useState("kimys@company.com, jung@company.com, ohsh@company.com");
  const [sendResult, setSendResult] = useState<SendEmailResponse | null>(null);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [submitted, setSubmitted] = useState("영업팀, 생산팀, 품질팀");
  const [deadline, setDeadline] = useState("2026-06-12 17:00");
  const [trackResult, setTrackResult] = useState<TrackResponse | null>(null);
  const [targetField, setTargetField] = useState("취합월");
  const [newValue, setNewValue] = useState("2026-06");
  const [oldValue, setOldValue] = useState("");
  const [updateResult, setUpdateResult] = useState<UpdateFieldsResponse | null>(null);
  const [styleCount, setStyleCount] = useState(0);
  const [styleInput, setStyleInput] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    getStyleMails().then((s) => setStyleCount(s.count)).catch(() => setStyleCount(0));
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
      const res = await collect({ subject, body, useGraph: true, useLlm: true, files });
      setResult(res);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  async function buildGuide() {
    setError(null);
    if (!subject.trim() || !body.trim()) {
      setError("메일 제목과 본문을 먼저 입력하세요.");
      return;
    }
    setGuideLoading(true);
    setGuide(null);
    setSendResult(null);
    try {
      const g = await createGuide(subject, body);
      setGuide(g);
      setDraftSubject(g.mail_draft.mail_subject);
      setDraftBody(g.mail_draft.mail_body);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setGuideLoading(false);
    }
  }

  async function approveAndSend() {
    setError(null);
    if (!guide) {
      setError("먼저 작성 가이드와 메일 초안을 생성하세요.");
      return;
    }
    const to = recipients.split(",").map((v) => v.trim()).filter(Boolean);
    if (to.length === 0) {
      setError("수신자 이메일을 1개 이상 입력하세요.");
      return;
    }
    if (!draftSubject.trim() || !draftBody.trim()) {
      setError("메일 제목과 본문을 확인하세요.");
      return;
    }
    setSendLoading(true);
    setSendResult(null);
    try {
      setSendResult(await sendEmail({
        to,
        subject: draftSubject,
        body: draftBody,
      }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSendLoading(false);
    }
  }

  async function runTrack() {
    setError(null);
    setTrackLoading(true);
    setTrackResult(null);
    try {
      const submittedList = submitted.split(",").map((v) => v.trim()).filter(Boolean);
      setTrackResult(await trackSubmissions(submittedList, deadline));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setTrackLoading(false);
    }
  }

  async function runUpdateFields() {
    setError(null);
    if (files.length === 0) {
      setError("일괄 수정할 엑셀 파일을 먼저 업로드하세요.");
      return;
    }
    setUpdateLoading(true);
    setUpdateResult(null);
    try {
      setUpdateResult(await updateFields({
        targetField,
        newValue,
        oldValue,
        files,
      }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setUpdateLoading(false);
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
            <span className="badge">Email {health.email_send_mode}{health.gmail_ready ? " ready" : ""}</span>
          </div>
        )}
      </header>

      <div className="grid">
        {/* 입력 패널 */}
        <section className="card">
          <h2>1. 취합 요청 메일</h2>
          <div className="row">
            <button className="ghost" onClick={loadSampleEmail}>내장 샘플 메일 불러오기</button>
            <button className="ghost" onClick={makeSamples}>샘플 엑셀 생성</button>
          </div>
          <p className="muted">
            ※ '내장 샘플'은 앱에 포함된 예시입니다. 실제 Gmail 메일은 Claude Code가
            Gmail MCP로 필요할 때 가져와 아래 제목/본문에 붙여넣습니다.
          </p>
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

      <section className="card wide">
        <h2>4. 작성 가이드 · Gmail 발송 · 제출 추적 · 공통항목 수정</h2>
        <div className="ops-grid">
          <div className="ops-panel">
            <h3>작성 가이드와 요청 메일 초안</h3>
            <div className="block">
              <p className="muted">내 과거 발송 스타일 샘플: <b>{styleCount}</b>개</p>
              <label>내가 작성한 메일 파일 업로드 (.txt / .md / .eml)</label>
              <input
                type="file"
                accept=".txt,.md,.eml"
                multiple
                onChange={async (e) => {
                  const picked = Array.from(e.target.files ?? []);
                  if (picked.length === 0) return;
                  const r = await uploadStyleMails(picked);
                  setStyleCount(r.count);
                  e.target.value = "";
                  alert(`스타일 샘플 ${r.saved.length}개 업로드됨 (총 ${r.count}개). '가이드/메일 초안 생성'을 누르면 반영됩니다.`);
                }}
              />
              <label>또는 메일 본문 직접 붙여넣기</label>
              <textarea
                value={styleInput}
                onChange={(e) => setStyleInput(e.target.value)}
                rows={3}
                placeholder="과거에 보냈던 요청 메일 본문을 붙여넣고 저장하면 초안 톤에 반영됩니다."
              />
              <button
                className="ghost inline"
                onClick={async () => {
                  if (!styleInput.trim()) return;
                  const r = await saveStyleMail("", styleInput.trim());
                  setStyleCount(r.count);
                  setStyleInput("");
                }}
              >
                붙여넣은 본문 저장
              </button>
            </div>
            <button className="ghost" onClick={buildGuide} disabled={guideLoading}>
              {guideLoading ? "생성 중…" : "가이드/메일 초안 생성"}
            </button>
            {guide && (
              <div className="block">
                <p><b>{guide.guide.guide_title}</b></p>
                {guide.style_used ? (
                  <span className="chip">내 과거 발송 스타일 반영됨 ({guide.style_sources.join(", ")})</span>
                ) : (
                  <span className="chip warn">스타일 샘플 없음 · 기본 톤</span>
                )}
                <pre>{guide.guide.guide_body}</pre>

                <h4>보낼 요청 메일 초안 (수정 가능)</h4>
                <label>메일 제목</label>
                <input value={draftSubject} onChange={(e) => setDraftSubject(e.target.value)} />
                <label>메일 본문</label>
                <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={8} />
                <label>수신자 이메일 (쉼표로 여러 명 입력)</label>
                <input
                  value={recipients}
                  onChange={(e) => setRecipients(e.target.value)}
                  placeholder="hong@company.com, kim@company.com, lee@company.com"
                />
                <button className="primary inline" onClick={approveAndSend} disabled={sendLoading}>
                  {sendLoading ? "발송 중…" : "승인 후 이메일 발송"}
                </button>
                {sendResult && (
                  <p className="oktext">
                    {sendResult.mode} / {sendResult.status} / {sendResult.message_id}
                    {sendResult.mode === "mock" && " (현재 mock 발송 — 실제 발송은 EMAIL_SEND_MODE=gmail 설정 필요)"}
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="ops-panel">
            <h3>제출 현황과 리마인드</h3>
            <p className="muted">
              현재는 파일 식별자 기반 mock 추적입니다. 실제 회신 메일 확인은
              Claude Code의 Gmail MCP로 수행할 수 있습니다(후속 확장).
            </p>
            <label>제출 식별자</label>
            <input value={submitted} onChange={(e) => setSubmitted(e.target.value)} />
            <label>마감일</label>
            <input value={deadline} onChange={(e) => setDeadline(e.target.value)} />
            <button className="ghost" onClick={runTrack} disabled={trackLoading}>
              {trackLoading ? "확인 중…" : "제출 현황 확인"}
            </button>
            {trackResult && (
              <div className="block">
                <p><b>{trackResult.summary}</b></p>
                <div className="chips">
                  {trackResult.missing_list.map((m) => (
                    <span className="chip warn" key={m.email}>{m.dept} 미제출</span>
                  ))}
                </div>
                {trackResult.reminder && (
                  <pre>{trackResult.reminder.reminder_mail_subject + "\n" + trackResult.reminder.reminder_mail_body}</pre>
                )}
              </div>
            )}
          </div>

          <div className="ops-panel">
            <h3>공통 항목 일괄 수정</h3>
            <label>대상 컬럼</label>
            <input value={targetField} onChange={(e) => setTargetField(e.target.value)} />
            <label>새 값</label>
            <input value={newValue} onChange={(e) => setNewValue(e.target.value)} />
            <label>기존 값 필터</label>
            <input value={oldValue} onChange={(e) => setOldValue(e.target.value)} placeholder="비우면 전체 적용" />
            <button className="ghost" onClick={runUpdateFields} disabled={updateLoading}>
              {updateLoading ? "수정 중…" : "업로드 파일 일괄 수정"}
            </button>
            {updateResult && (
              <div className="block">
                <p><b>변경 셀 {updateResult.update_count}개</b></p>
                <div className="downloads">
                  {updateResult.downloads.map((href) => (
                    <a className="ghost" href={href} key={href}>수정 파일</a>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>
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

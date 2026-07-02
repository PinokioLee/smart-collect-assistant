import { useEffect, useState } from "react";
import {
  collect,
  createGuide,
  genSamples,
  getHealth,
  getSampleEmail,
  getStyleMails,
  saveStyleMail,
  uploadStyleMails,
  sendRequestMail,
  trackSubmissions,
  updateFields,
  type GuideResponse,
  type Health,
  type SendRequestMailResponse,
  type TrackResponse,
  type UpdateFieldsResponse,
} from "./api";
import type { CollectResponse } from "./types";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 1. 취합 요청 메일 보내기
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [styleCount, setStyleCount] = useState(0);
  const [styleInput, setStyleInput] = useState("");
  const [guide, setGuide] = useState<GuideResponse | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [attachFiles, setAttachFiles] = useState<File[]>([]);
  const [recipients, setRecipients] = useState("kimys@company.com, jung@company.com, ohsh@company.com");
  const [sendLoading, setSendLoading] = useState(false);
  const [sendResult, setSendResult] = useState<SendRequestMailResponse | null>(null);

  // 2. 제출 엑셀 검증/병합
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CollectResponse | null>(null);

  // 3. 제출 현황 & 리마인드
  const [submitted, setSubmitted] = useState("영업팀, 생산팀, 품질팀");
  const [deadline, setDeadline] = useState("2026-06-12 17:00");
  const [trackLoading, setTrackLoading] = useState(false);
  const [trackResult, setTrackResult] = useState<TrackResponse | null>(null);

  // 4. 공통 항목 일괄 수정
  const [updateFilesList, setUpdateFilesList] = useState<File[]>([]);
  const [targetField, setTargetField] = useState("취합월");
  const [newValue, setNewValue] = useState("2026-06");
  const [oldValue, setOldValue] = useState("");
  const [updateLoading, setUpdateLoading] = useState(false);
  const [updateResult, setUpdateResult] = useState<UpdateFieldsResponse | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    getStyleMails().then((s) => setStyleCount(s.count)).catch(() => setStyleCount(0));
  }, []);

  async function loadSampleEmail() {
    const s = await getSampleEmail();
    setSubject(s.subject);
    setBody(s.body);
  }

  async function uploadStyle(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length === 0) return;
    const r = await uploadStyleMails(picked);
    setStyleCount(r.count);
    e.target.value = "";
    alert(`스타일 샘플 ${r.saved.length}개 저장됨 (총 ${r.count}개). '요청 메일 초안 생성'에 반영됩니다.`);
  }

  async function saveStylePaste() {
    if (!styleInput.trim()) return;
    const r = await saveStyleMail("", styleInput.trim());
    setStyleCount(r.count);
    setStyleInput("");
  }

  async function buildGuide() {
    setError(null);
    if (!subject.trim() || !body.trim()) {
      setError("받은 취합 요청의 제목과 본문을 먼저 입력하세요.");
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

  async function sendRequest() {
    setError(null);
    if (!draftSubject.trim() || !draftBody.trim()) {
      setError("보낼 메일의 제목과 본문을 입력하세요. (초안 생성 또는 직접 작성)");
      return;
    }
    const to = recipients.split(",").map((v) => v.trim()).filter(Boolean);
    if (to.length === 0) {
      setError("수신자 이메일을 1개 이상 입력하세요.");
      return;
    }
    setSendLoading(true);
    setSendResult(null);
    try {
      setSendResult(await sendRequestMail({ to: recipients, subject: draftSubject, body: draftBody, files: attachFiles }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSendLoading(false);
    }
  }

  async function makeSamples() {
    await genSamples();
    alert("샘플 제출 엑셀을 data/samples 에 생성했습니다. 아래 파일 선택에서 업로드하세요.");
  }

  async function run() {
    setError(null);
    if (!subject.trim() || !body.trim()) {
      setError("검증 기준을 분석하려면 1단계의 취합 요청 제목/본문이 필요합니다.");
      return;
    }
    if (files.length === 0) {
      setError("회신받은 제출 엑셀을 1개 이상 업로드하세요.");
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
    if (updateFilesList.length === 0) {
      setError("일괄 수정할 엑셀 파일을 먼저 업로드하세요.");
      return;
    }
    setUpdateLoading(true);
    setUpdateResult(null);
    try {
      setUpdateResult(await updateFields({ targetField, newValue, oldValue, files: updateFilesList }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setUpdateLoading(false);
    }
  }

  const vr = result?.validation_result;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand-mark">
          <div className="brand-glyph">SC</div>
          <div>
            <h1 className="brand-name">Smart Collect</h1>
            <p className="brand-thesis">취합 요청 메일부터 엑셀 검증·병합까지, 한 흐름으로</p>
          </div>
        </div>
        {health && (
          <div className="pills">
            <Pill on={health.azure_ready} label={`Azure ${health.azure_ready ? "" : "휴리스틱"}`.trim()} />
            <Pill on={health.use_rag} label="RAG" />
            <Pill on={health.use_langfuse} label="Langfuse" />
            <Pill on={health.email_send_mode === "gmail"} label={`Email ${health.email_send_mode}`} />
          </div>
        )}
      </header>

      {error && <p className="error">⚠ {error}</p>}

      <div className="board">
        {/* ===== 01 요청 ===== */}
        <section className="lane">
          <div className="lane-head">
            <div className="lane-eyebrow">
              <span className="lane-no">01</span>
              <span className="lane-kicker">요청</span>
            </div>
            <h2 className="lane-title">취합 요청 메일 보내기</h2>
            <p className="lane-desc">받은 요청 → 내 스타일 초안 → 양식 첨부·발송</p>
          </div>
          <div className="lane-body">
            <div className="sub">
              <div className="sub-label"><span className="step-chip">A</span> 받은 취합 요청 내용</div>
              <div className="row">
                <button className="ghost" onClick={loadSampleEmail}>내장 샘플 메일 불러오기</button>
              </div>
              <p className="hint">실제 Gmail 메일은 Claude Code가 Gmail MCP로 가져와 아래에 붙여넣습니다.</p>
              <label>제목</label>
              <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="예: 2026년 6월 시스템 개선 요청사항 취합" />
              <label>본문 (직접 붙여넣기 가능)</label>
              <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder="작성 항목, 마감일, 긴급도 기준 등을 포함한 본문" />
            </div>

            <div className="sub">
              <div className="sub-label">
                <span className="step-chip">B</span> 내 발송 스타일 <span className="opt">선택 · {styleCount}개</span>
              </div>
              <label>내가 작성한 메일 파일 (.txt / .md / .eml)</label>
              <input type="file" accept=".txt,.md,.eml" multiple onChange={uploadStyle} />
              <label>또는 과거 메일 본문 붙여넣기</label>
              <textarea value={styleInput} onChange={(e) => setStyleInput(e.target.value)} rows={2} placeholder="붙여넣고 저장하면 초안 톤에 반영됩니다." />
              <button className="ghost inline" onClick={saveStylePaste}>붙여넣은 본문 저장</button>
            </div>

            <div className="sub">
              <div className="sub-label"><span className="step-chip">C</span> 요청 메일 초안 &amp; 발송</div>
              <button className="primary block-btn" onClick={buildGuide} disabled={guideLoading}>
                {guideLoading ? "생성 중…" : "요청 메일 초안 생성 (내 스타일)"}
              </button>

              <div className="dispatch">
                <h4>보낼 요청 메일 — 수정·직접 작성 가능</h4>
                {guide && (
                  <span className={`chip badge-inline${guide.style_used ? "" : " warn"}`}>
                    {guide.style_used ? `내 발송 스타일 반영됨 (${guide.style_sources.join(", ")})` : "스타일 샘플 없음 · 기본 톤"}
                  </span>
                )}
                <label>메일 제목</label>
                <input value={draftSubject} onChange={(e) => setDraftSubject(e.target.value)} />
                <label>메일 본문</label>
                <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={7} />
                <label>첨부 양식 엑셀 (요청과 함께 받은 양식)</label>
                <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setAttachFiles(Array.from(e.target.files ?? []))} />
                {attachFiles.length > 0 && (
                  <ul className="filelist">{attachFiles.map((f) => (<li key={f.name}>📎 {f.name}</li>))}</ul>
                )}
                <label>수신자 이메일 (쉼표로 여러 명)</label>
                <input value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="hong@company.com, kim@company.com" />
                <button className="primary inline" onClick={sendRequest} disabled={sendLoading}>
                  {sendLoading ? "발송 중…" : "메일 보내기"}
                </button>
                {sendResult && (
                  <p className="oktext">
                    {sendResult.mode} · {sendResult.status} · {sendResult.message_id}
                    {sendResult.attachments.length > 0 && ` · 첨부 ${sendResult.attachments.length}개`}
                    {sendResult.mode === "mock" && "  (mock 발송)"}
                  </p>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ===== 02 검증 ===== */}
        <section className="lane">
          <div className="lane-head">
            <div className="lane-eyebrow">
              <span className="lane-no">02</span>
              <span className="lane-kicker">검증</span>
            </div>
            <h2 className="lane-title">제출 엑셀 검증 · 병합</h2>
            <p className="lane-desc">회신 첨부 검증 → 정상만 병합 → 취합 엑셀 다운로드</p>
          </div>
          <div className="lane-body">
            <div className="row">
              <button className="ghost" onClick={makeSamples}>샘플 제출 엑셀 생성</button>
            </div>
            <label>회신받은 제출 엑셀 업로드</label>
            <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
            {files.length > 0 && (
              <ul className="filelist">{files.map((f) => (<li key={f.name}>📄 {f.name}</li>))}</ul>
            )}
            <button className="primary block-btn" onClick={run} disabled={loading}>
              {loading ? "처리 중…" : "검증 · 병합 실행"}
            </button>

            {result && vr && (
              <div className="result">
                <div className="stats">
                  <Stat label="파일" value={vr.total_files} />
                  <Stat label="전체 행" value={vr.total_rows} />
                  <Stat label="정상" value={vr.valid_rows} tone="ok" />
                  <Stat label="오류" value={vr.error_rows} tone={vr.error_rows ? "bad" : "ok"} />
                </div>

                {result.extracted_requirements && (
                  <div className="block">
                    <h4>메일 분석</h4>
                    <p className="field-line"><b>제출 기한</b> · {result.extracted_requirements.deadline ?? "확인 필요"}</p>
                    <div className="chips">
                      {result.extracted_requirements.required_fields.map((f) => (<span className="chip" key={f}>{f}</span>))}
                    </div>
                  </div>
                )}

                {result.validation_rules && (
                  <div className="block">
                    <h4>적용된 검증 규칙</h4>
                    <p className="field-line"><b>필수</b> · {result.validation_rules.required_columns.join(", ") || "-"}</p>
                    <p className="field-line"><b>날짜</b> · {result.validation_rules.date_columns.join(", ") || "-"}</p>
                    <p className="field-line"><b>코드값</b> · {Object.entries(result.validation_rules.code_rules).map(([k, v]) => `${k}=${v.join("/")}`).join(", ") || "-"}</p>
                    <p className="field-line"><b>중복키</b> · {result.validation_rules.duplicate_keys.join(", ") || "-"}</p>
                  </div>
                )}

                {vr.error_details.length > 0 && (
                  <div className="block">
                    <h4>오류 상세 ({vr.error_details.length})</h4>
                    <div className="table-wrap">
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
                  </div>
                )}

                <div className="block downloads">
                  {result.downloads.merged && (<a className="primary" href={result.downloads.merged}>⬇ 취합 엑셀</a>)}
                  {result.downloads.error && (<a className="ghost" href={result.downloads.error}>⬇ 오류 보고서</a>)}
                </div>

                <div className="block">
                  <h4>에이전트 실행 흐름</h4>
                  <div className="flow">
                    {result.agent_handoff_history.map((h, i) => (<span className="node" key={i}>{h.split(":")[1] ?? h}</span>))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ===== 03 추적 ===== */}
        <section className="lane">
          <div className="lane-head">
            <div className="lane-eyebrow">
              <span className="lane-no">03</span>
              <span className="lane-kicker">추적</span>
            </div>
            <h2 className="lane-title">제출 현황 · 리마인드</h2>
            <p className="lane-desc">제출 현황 확인 · 미제출자 리마인드 초안</p>
          </div>
          <div className="lane-body">
            <p className="hint">현재는 파일 식별자 기반 mock 추적입니다. 실제 회신 확인은 Gmail MCP로 수행할 수 있습니다(후속 확장).</p>
            <label>제출 식별자 (쉼표 구분)</label>
            <input value={submitted} onChange={(e) => setSubmitted(e.target.value)} />
            <label>마감일</label>
            <input value={deadline} onChange={(e) => setDeadline(e.target.value)} />
            <button className="primary block-btn" onClick={runTrack} disabled={trackLoading}>
              {trackLoading ? "확인 중…" : "제출 현황 확인 · 리마인드"}
            </button>
            {trackResult && (
              <div className="result">
                <p className="field-line"><b>{trackResult.summary}</b></p>
                <div className="chips">
                  {trackResult.missing_list.map((m) => (<span className="chip warn" key={m.email}>{m.dept} 미제출</span>))}
                </div>
                {trackResult.reminder && (
                  <pre>{trackResult.reminder.reminder_mail_subject + "\n" + trackResult.reminder.reminder_mail_body}</pre>
                )}
              </div>
            )}
          </div>
        </section>

        {/* ===== 04 수정 ===== */}
        <section className="lane">
          <div className="lane-head">
            <div className="lane-eyebrow">
              <span className="lane-no">04</span>
              <span className="lane-kicker">수정</span>
            </div>
            <h2 className="lane-title">공통 항목 일괄 수정</h2>
            <p className="lane-desc">여러 파일의 공통 컬럼을 한 번에 수정 (원본 보존)</p>
          </div>
          <div className="lane-body">
            <label>수정할 엑셀 파일 업로드</label>
            <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setUpdateFilesList(Array.from(e.target.files ?? []))} />
            {updateFilesList.length > 0 && (
              <ul className="filelist">{updateFilesList.map((f) => (<li key={f.name}>📄 {f.name}</li>))}</ul>
            )}
            <label>대상 컬럼</label>
            <input value={targetField} onChange={(e) => setTargetField(e.target.value)} />
            <label>새 값</label>
            <input value={newValue} onChange={(e) => setNewValue(e.target.value)} />
            <label>기존 값 필터 (비우면 전체 적용)</label>
            <input value={oldValue} onChange={(e) => setOldValue(e.target.value)} placeholder="비우면 전체 적용" />
            <button className="primary block-btn" onClick={runUpdateFields} disabled={updateLoading}>
              {updateLoading ? "수정 중…" : "업로드 파일 일괄 수정"}
            </button>
            {updateResult && (
              <div className="result">
                <p className="field-line"><b>변경 셀 {updateResult.update_count}개</b></p>
                <div className="downloads">
                  {updateResult.downloads.map((href, i) => (<a className="primary" href={href} key={href}>⬇ 수정 파일 {updateResult.downloads.length > 1 ? i + 1 : ""}</a>))}
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Pill({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={`pill${on ? " on" : ""}`}>
      <span className="dot" />
      {label}
    </span>
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

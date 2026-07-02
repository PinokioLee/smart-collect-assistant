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
    alert(`스타일 샘플 ${r.saved.length}개 업로드됨 (총 ${r.count}개). '요청 메일 초안 생성'을 누르면 반영됩니다.`);
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
      setSendResult(await sendRequestMail({
        to: recipients,
        subject: draftSubject,
        body: draftBody,
        files: attachFiles,
      }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSendLoading(false);
    }
  }

  async function makeSamples() {
    await genSamples();
    alert("샘플 제출 엑셀 3개를 data/samples 에 생성했습니다. 아래 파일 선택에서 업로드하세요.");
  }

  async function run() {
    setError(null);
    if (!subject.trim() || !body.trim()) {
      setError("검증 기준을 분석하려면 1번의 취합 요청 제목/본문이 필요합니다.");
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
      setUpdateResult(await updateFields({
        targetField,
        newValue,
        oldValue,
        files: updateFilesList,
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
        <p className="sub">① 요청 메일 발송 → ② 제출 엑셀 검증·병합 → ③ 제출 현황·리마인드 → ④ 공통 항목 수정</p>
        {health && (
          <div className="badges">
            <span className="badge">Azure {health.azure_ready ? "ON" : "휴리스틱"}</span>
            <span className="badge">RAG {health.use_rag ? "ON" : "OFF"}</span>
            <span className="badge">Langfuse {health.use_langfuse ? "ON" : "OFF"}</span>
            <span className="badge">Email {health.email_send_mode}{health.gmail_ready ? " ready" : ""}</span>
          </div>
        )}
        {error && <p className="error">⚠ {error}</p>}
      </header>

      {/* ===== 1. 취합 요청 메일 보내기 ===== */}
      <section className="card">
        <h2>1. 취합 요청 메일 보내기</h2>
        <p className="muted">받은 취합 요청을 바탕으로, 제출자에게 보낼 요청 메일을 내 스타일로 작성해 발송합니다.</p>

        <h3>① 받은 취합 요청 내용</h3>
        <div className="row">
          <button className="ghost" onClick={loadSampleEmail}>내장 샘플 메일 불러오기</button>
        </div>
        <p className="muted">※ 실제 Gmail 메일은 Claude Code가 Gmail MCP로 가져와 아래에 붙여넣습니다.</p>
        <label>제목</label>
        <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="예: 2026년 6월 시스템 개선 요청사항 취합" />
        <label>본문 (직접 붙여넣기 가능)</label>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} placeholder="작성 항목, 마감일, 긴급도 기준 등을 포함한 본문" />

        <h3>② 내 발송 스타일 반영 (선택) — 현재 {styleCount}개</h3>
        <label>내가 작성한 메일 파일 업로드 (.txt / .md / .eml)</label>
        <input type="file" accept=".txt,.md,.eml" multiple onChange={uploadStyle} />
        <label>또는 과거 메일 본문 직접 붙여넣기</label>
        <textarea value={styleInput} onChange={(e) => setStyleInput(e.target.value)} rows={2} placeholder="과거에 보냈던 요청 메일 본문을 붙여넣고 저장하면 초안 톤에 반영됩니다." />
        <button className="ghost inline" onClick={saveStylePaste}>붙여넣은 본문 저장</button>

        <button className="primary" onClick={buildGuide} disabled={guideLoading}>
          {guideLoading ? "생성 중…" : "③ 요청 메일 초안 생성 (내 스타일)"}
        </button>

        <div className="block">
          <h3>④ 보낼 요청 메일 (수정 가능 · 직접 작성도 가능)</h3>
          {guide && (guide.style_used ? (
            <span className="chip">내 과거 발송 스타일 반영됨 ({guide.style_sources.join(", ")})</span>
          ) : (
            <span className="chip warn">스타일 샘플 없음 · 기본 톤</span>
          ))}
          <label>메일 제목</label>
          <input value={draftSubject} onChange={(e) => setDraftSubject(e.target.value)} />
          <label>메일 본문</label>
          <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={8} />
          <label>첨부 양식 엑셀 (요청과 함께 받은 양식을 그대로 첨부)</label>
          <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setAttachFiles(Array.from(e.target.files ?? []))} />
          {attachFiles.length > 0 && (
            <ul className="filelist">
              {attachFiles.map((f) => (<li key={f.name}>📎 {f.name}</li>))}
            </ul>
          )}
          <label>수신자 이메일 (쉼표로 여러 명 입력)</label>
          <input value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="hong@company.com, kim@company.com, lee@company.com" />
          <button className="primary inline" onClick={sendRequest} disabled={sendLoading}>
            {sendLoading ? "발송 중…" : "메일 보내기"}
          </button>
          {sendResult && (
            <p className="oktext">
              {sendResult.mode} / {sendResult.status} / {sendResult.message_id}
              {sendResult.attachments.length > 0 && ` / 첨부 ${sendResult.attachments.length}개`}
              {sendResult.mode === "mock" && " (현재 mock 발송 — 실제 발송은 EMAIL_SEND_MODE=gmail 설정 필요)"}
            </p>
          )}
        </div>
      </section>

      {/* ===== 2. 제출 엑셀 검증 · 병합 ===== */}
      <section className="card wide">
        <h2>2. 제출 엑셀 검증 · 병합</h2>
        <p className="muted">회신받은 이메일의 첨부 엑셀을 모두 업로드해 검증하고, 정상 데이터만 병합합니다. (검증 기준은 1번 요청 내용에서 자동 분석)</p>
        <div className="row">
          <button className="ghost" onClick={makeSamples}>샘플 제출 엑셀 생성</button>
        </div>
        <label>회신받은 제출 엑셀 업로드</label>
        <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        {files.length > 0 && (
          <ul className="filelist">
            {files.map((f) => (<li key={f.name}>📄 {f.name}</li>))}
          </ul>
        )}
        <button className="primary" onClick={run} disabled={loading}>
          {loading ? "처리 중…" : "검증 · 병합 실행"}
        </button>

        {result && vr && (
          <div className="block">
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
                <a className="primary" href={result.downloads.merged}>⬇ 취합(병합) 엑셀 다운로드</a>
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
          </div>
        )}
      </section>

      {/* ===== 3. 제출 현황 & 리마인드 ===== */}
      <section className="card wide">
        <h2>3. 제출 현황 · 리마인드</h2>
        <p className="muted">
          현재는 파일 식별자 기반 mock 추적입니다. 실제 회신 메일 확인은
          Claude Code의 Gmail MCP로 수행할 수 있습니다(후속 확장).
        </p>
        <label>제출 식별자 (쉼표 구분)</label>
        <input value={submitted} onChange={(e) => setSubmitted(e.target.value)} />
        <label>마감일</label>
        <input value={deadline} onChange={(e) => setDeadline(e.target.value)} />
        <button className="ghost" onClick={runTrack} disabled={trackLoading}>
          {trackLoading ? "확인 중…" : "제출 현황 확인 · 리마인드 생성"}
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
      </section>

      {/* ===== 4. 공통 항목 일괄 수정 ===== */}
      <section className="card wide">
        <h2>4. 공통 항목 일괄 수정</h2>
        <p className="muted">여러 엑셀 파일의 공통 컬럼 값을 한 번에 수정합니다. (원본은 보존, 수정본 별도 저장)</p>
        <label>수정할 엑셀 파일 업로드</label>
        <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setUpdateFilesList(Array.from(e.target.files ?? []))} />
        {updateFilesList.length > 0 && (
          <ul className="filelist">
            {updateFilesList.map((f) => (<li key={f.name}>📄 {f.name}</li>))}
          </ul>
        )}
        <label>대상 컬럼</label>
        <input value={targetField} onChange={(e) => setTargetField(e.target.value)} />
        <label>새 값</label>
        <input value={newValue} onChange={(e) => setNewValue(e.target.value)} />
        <label>기존 값 필터 (비우면 전체 적용)</label>
        <input value={oldValue} onChange={(e) => setOldValue(e.target.value)} placeholder="비우면 전체 적용" />
        <button className="ghost" onClick={runUpdateFields} disabled={updateLoading}>
          {updateLoading ? "수정 중…" : "업로드 파일 일괄 수정"}
        </button>
        {updateResult && (
          <div className="block">
            <p><b>변경 셀 {updateResult.update_count}개</b></p>
            <div className="downloads">
              {updateResult.downloads.map((href) => (
                <a className="ghost" href={href} key={href}>수정 파일 다운로드</a>
              ))}
            </div>
          </div>
        )}
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

import { useEffect, useState } from "react";
import {
  collect,
  createGuide,
  genHardSamples,
  genProjectSamples,
  genSamples,
  inboxIngest,
  inboxQueue,
  inboxSend,
  getAgentJobs,
  getSchedule,
  setSchedule,
  scheduleRunNow,
  type IngestResult,
  type CollectionJob,
  type ScheduleStatus,
  getHealth,
  getSampleEmail,
  getStyleMails,
  saveStyleMail,
  uploadStyleMails,
  sendRequestMail,
  syncCommonFields,
  trackSubmissions,
  designTemplate,
  buildTemplate,
  type GuideResponse,
  type Health,
  type SendRequestMailResponse,
  type SyncCommonFieldsResponse,
  type TrackResponse,
  type TemplateSpec,
  type BuildTemplateResponse,
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
  // 양식 자동 설계 (Template Design Agent)
  const [templateIntent, setTemplateIntent] = useState(
    "프로젝트별 월 실적을 걷을 건데 프로젝트번호, 담당자, 매출액, 진행상태(정상/지연/보류), 마감일자 받고 싶어"
  );
  const [templateSpec, setTemplateSpec] = useState<TemplateSpec | null>(null);
  const [templateLlmUsed, setTemplateLlmUsed] = useState(false);
  const [templateDesignLoading, setTemplateDesignLoading] = useState(false);
  const [templateBuilt, setTemplateBuilt] = useState<BuildTemplateResponse | null>(null);
  const [templateBuildLoading, setTemplateBuildLoading] = useState(false);
  const [useTemplateForFlow, setUseTemplateForFlow] = useState(true);

  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CollectResponse | null>(null);

  // 3. 제출 현황 & 리마인드
  const [submitted, setSubmitted] = useState("영업팀, 생산팀, 품질팀");
  const [deadline, setDeadline] = useState("2026-06-12 17:00");
  const [trackLoading, setTrackLoading] = useState(false);
  const [trackResult, setTrackResult] = useState<TrackResponse | null>(null);
  const [reminderSubject, setReminderSubject] = useState("");
  const [reminderBody, setReminderBody] = useState("");
  const [reminderRecipients, setReminderRecipients] = useState("");
  const [reminderAttach, setReminderAttach] = useState<File[]>([]);
  const [reminderSendLoading, setReminderSendLoading] = useState(false);
  const [reminderSendResult, setReminderSendResult] = useState<SendRequestMailResponse | null>(null);

  // 5. 수신함 자동 분류
  const [inboxLoading, setInboxLoading] = useState(false);
  const [inbox, setInbox] = useState<IngestResult | null>(null);
  const [inboxMsg, setInboxMsg] = useState("");
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [collectionJobs, setCollectionJobs] = useState<CollectionJob[]>([]);

  // 5-b. 자동 수집 스케줄
  const [sched, setSched] = useState<ScheduleStatus | null>(null);
  const [schedEnabled, setSchedEnabled] = useState(false);
  const [schedMode, setSchedMode] = useState<"times" | "interval" | "weekly">("times");
  const [schedTimes, setSchedTimes] = useState<string[]>(["09:00", "14:00", "19:00"]);
  const [schedInterval, setSchedInterval] = useState(1);
  const [schedWeekday, setSchedWeekday] = useState(0);
  const [schedWeeklyTime, setSchedWeeklyTime] = useState("09:00");
  const [schedSaving, setSchedSaving] = useState(false);

  function applyStatus(s: ScheduleStatus) {
    setSched(s);
    setSchedEnabled(s.config.enabled);
    setSchedMode(s.config.mode);
    setSchedTimes(s.config.times?.length ? s.config.times : ["09:00"]);
    setSchedInterval(s.config.interval_hours || 1);
    setSchedWeekday(s.config.weekday ?? 0);
    setSchedWeeklyTime(s.config.weekly_time || "09:00");
  }

  useEffect(() => {
    getSchedule().then(applyStatus).catch(() => {});
    getAgentJobs().then((r) => setCollectionJobs(r.jobs)).catch(() => {});
    inboxQueue().then((q) => setInbox({
      fetched: 0,
      processed_new: 0,
      skipped: 0,
      by_status: q.counts,
      queue: q.queue,
      read_mode: q.read_mode,
    })).catch(() => {});
  }, []);

  async function saveSchedule() {
    setSchedSaving(true);
    setError(null);
    try {
      const s = await setSchedule({
        enabled: schedEnabled,
        mode: schedMode,
        interval_hours: schedInterval,
        times: schedTimes,
        weekday: schedWeekday,
        weekly_time: schedWeeklyTime,
      });
      applyStatus(s);
      setInboxMsg("스케줄을 저장했습니다.");
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSchedSaving(false);
    }
  }

  async function runScheduleNow() {
    setSchedSaving(true);
    try {
      const r = await scheduleRunNow();
      applyStatus(r.status);
      const q = await inboxQueue();
      setInbox({
        fetched: r.status.last_summary?.fetched ?? 0,
        processed_new: r.status.last_summary?.processed_new ?? 0,
        skipped: 0,
        by_status: q.counts,
        queue: q.queue,
        read_mode: q.read_mode,
      });
      setCollectionJobs((await getAgentJobs()).jobs);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSchedSaving(false);
    }
  }

  // 4. 공통 항목 일괄 수정
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [targetFiles, setTargetFiles] = useState<File[]>([]);
  const [updateLoading, setUpdateLoading] = useState(false);
  const [updateResult, setUpdateResult] = useState<SyncCommonFieldsResponse | null>(null);
  const [projectSampleInfo, setProjectSampleInfo] = useState<string | null>(null);

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
      const tid = useTemplateForFlow && templateBuilt ? templateBuilt.template_id : undefined;
      setSendResult(await sendRequestMail({ to: recipients, subject: draftSubject, body: draftBody, files: attachFiles, templateId: tid }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSendLoading(false);
    }
  }

  async function designForm() {
    setError(null);
    if (!templateIntent.trim()) {
      setError("걷고 싶은 내용을 자연어로 입력하세요.");
      return;
    }
    setTemplateDesignLoading(true);
    setTemplateBuilt(null);
    try {
      const r = await designTemplate(templateIntent, true);
      setTemplateSpec(r.template_spec);
      setTemplateLlmUsed(r.llm_used);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setTemplateDesignLoading(false);
    }
  }

  function updateColumn(idx: number, patch: Partial<TemplateSpec["columns"][number]>) {
    setTemplateSpec((prev) => {
      if (!prev) return prev;
      const columns = prev.columns.map((c, i) => (i === idx ? { ...c, ...patch } : c));
      return { ...prev, columns };
    });
  }

  function removeColumn(idx: number) {
    setTemplateSpec((prev) =>
      prev ? { ...prev, columns: prev.columns.filter((_, i) => i !== idx) } : prev
    );
  }

  function addColumn() {
    setTemplateSpec((prev) =>
      prev
        ? {
            ...prev,
            columns: [
              ...prev.columns,
              { name: "새 컬럼", dtype: "text", required: false, allowed_values: [], date_format: "YYYY-MM-DD", example: null, description: null },
            ],
          }
        : prev
    );
  }

  async function buildForm() {
    if (!templateSpec) return;
    setError(null);
    setTemplateBuildLoading(true);
    try {
      const r = await buildTemplate(templateSpec);
      setTemplateBuilt(r);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setTemplateBuildLoading(false);
    }
  }

  async function makeSamples() {
    await genSamples();
    alert("샘플 제출 엑셀을 data/samples 에 생성했습니다. 아래 파일 선택에서 업로드하세요.");
  }

  async function makeHardSamples() {
    try {
      const r = await genHardSamples();
      const exp = r.expected;
      alert(
        "현실 난이도 하드 샘플을 data/samples/hard 에 생성했습니다.\n" +
          `기대 결과: ${exp.total_rows}행 중 오류 ${exp.error_rows}행 · 오류유형 ${exp.error_types.length}종 · ` +
          `자동교정 ${exp.self_correction_applied}/${exp.self_correction_fixable}건.\n` +
          "필수값 누락 · 필수 컬럼 누락(개명) · 날짜형식 · 코드값 · 파일 간 중복 + 통화 숫자/스키마 드리프트를 포함합니다.\n" +
          "탐색기에서 data/samples/hard 파일을 위 업로드 칸에 올린 뒤 실행하세요."
      );
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    }
  }

  async function runInboxIngest() {
    setInboxLoading(true);
    setError(null);
    setInboxMsg("");
    try {
      const r = await inboxIngest(true);
      setInbox(r);
      setCollectionJobs((await getAgentJobs()).jobs);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setInboxLoading(false);
    }
  }

  async function approveSend(id: string) {
    setSendingId(id);
    setError(null);
    try {
      await inboxSend(id);
      const q = await inboxQueue();
      setInbox((prev) => (prev ? { ...prev, queue: q.queue, by_status: q.counts } : prev));
      setCollectionJobs((await getAgentJobs()).jobs);
      setInboxMsg("초안을 승인하여 발송했습니다 (기본 mock 발송).");
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setSendingId(null);
    }
  }

  async function run() {
    setError(null);
    if (files.length === 0) {
      setError("회신받은 제출 엑셀을 1개 이상 업로드하세요.");
      return;
    }
    // 01 제목/본문이 비어 있으면 내장 샘플 메일을 자동으로 불러와 그대로 사용
    let subj = subject;
    let bod = body;
    if (!subj.trim() || !bod.trim()) {
      const s = await getSampleEmail();
      subj = s.subject;
      bod = s.body;
      setSubject(s.subject);
      setBody(s.body);
    }
    setLoading(true);
    setResult(null);
    try {
      const tid = useTemplateForFlow && templateBuilt ? templateBuilt.template_id : undefined;
      const res = await collect({ subject: subj, body: bod, useGraph: true, useLlm: true, files, templateId: tid });
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
    setReminderSendResult(null);
    try {
      const submittedList = submitted.split(",").map((v) => v.trim()).filter(Boolean);
      const t = await trackSubmissions(submittedList, deadline);
      setTrackResult(t);
      if (t.reminder) {
        setReminderSubject(t.reminder.reminder_mail_subject);
        setReminderBody(t.reminder.reminder_mail_body);
      }
      setReminderRecipients(t.missing_list.map((m) => m.email).filter(Boolean).join(", "));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setTrackLoading(false);
    }
  }

  async function sendReminder() {
    setError(null);
    if (!reminderSubject.trim() || !reminderBody.trim()) {
      setError("리마인드 메일 제목과 본문을 입력하세요. (현황 확인 또는 직접 작성)");
      return;
    }
    const to = reminderRecipients.split(",").map((v) => v.trim()).filter(Boolean);
    if (to.length === 0) {
      setError("리마인드 수신자 이메일을 1개 이상 입력하세요.");
      return;
    }
    setReminderSendLoading(true);
    setReminderSendResult(null);
    try {
      setReminderSendResult(await sendRequestMail({ to: reminderRecipients, subject: reminderSubject, body: reminderBody, files: reminderAttach }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setReminderSendLoading(false);
    }
  }

  async function makeProjectSamples() {
    setError(null);
    try {
      const r = await genProjectSamples();
      setProjectSampleInfo(
        `프로젝트 샘플 5개 생성 완료. 기준 파일: ${r.reference.split(/[\\/]/).pop()} / 대상 파일 ${r.targets.length}개`
      );
      alert("프로젝트 공통 항목 샘플 5개를 data/samples/project_common 에 생성했습니다.");
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    }
  }

  async function runUpdateFields() {
    setError(null);
    if (!referenceFile) {
      setError("기준 파일을 먼저 업로드하세요.");
      return;
    }
    if (targetFiles.length === 0) {
      setError("수정 대상 파일을 1개 이상 업로드하세요.");
      return;
    }
    setUpdateLoading(true);
    setUpdateResult(null);
    try {
      setUpdateResult(await syncCommonFields({ referenceFile, targetFiles }));
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e));
    } finally {
      setUpdateLoading(false);
    }
  }

  const vr = result?.validation_result;
  const sc = result?.self_correction;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand-mark">
          <div className="brand-glyph">SC</div>
          <div>
            <h1 className="brand-name">Smart Collect</h1>
            <p className="brand-thesis">메일 이해·검증전략·자가교정을 LLM이 판단하고 코드가 검증하는 멀티에이전트 세션</p>
          </div>
        </div>
        {health && (
          <div className="pills">
            <Pill on={health.azure_ready} label={`Azure ${health.azure_ready ? "" : "휴리스틱"}`.trim()} />
            <Pill on={health.use_rag} label="RAG" />
            <Pill on={health.use_langfuse} label="Langfuse" />
            <Pill on={health.email_send_mode === "gmail"} label={`Email ${health.email_send_mode}`} />
            <Pill on={health.gmail_read_ready} label="Gmail 수신" />
            <Pill on={health.auto_send_enabled} label={`자동발송 ${health.auto_send_enabled ? "ON" : "OFF"}`} />
          </div>
        )}
      </header>

      {error && <p className="error">⚠ {error}</p>}

      <div className="screen">
        {/* ===== 02 양식 설계 ===== */}
        <section className="lane" style={{ order: 2 }}>
          <div className="lane-head">
            <div className="lane-eyebrow"><span className="lane-no">02</span><span className="lane-kicker">양식 설계</span></div>
            <h2 className="lane-title">취합 양식 자동 생성</h2>
            <p className="lane-desc">자연어로 원하는 항목 → 🧠 AI가 컬럼 설계 → 엑셀 양식 생성 · 이 양식이 곧 검증 기준</p>
          </div>
          <div className="lane-body">
            <div className="split">
              <div className="col">
                <div className="sub">
                  <div className="sub-label"><span className="step-chip">A</span> 어떤 걸 걷고 싶으세요? (자연어)</div>
                  <textarea
                    value={templateIntent}
                    onChange={(e) => setTemplateIntent(e.target.value)}
                    rows={4}
                    placeholder="예: 프로젝트번호, 담당자, 매출액, 진행상태(정상/지연/보류), 마감일자 받고 싶어"
                  />
                  <p className="hint">항목은 쉼표로 구분하고, 보기가 정해진 항목은 <code>진행상태(정상/지연/보류)</code>처럼 괄호로 적으면 드롭다운으로 만듭니다.</p>
                  <button className="primary block-btn" onClick={designForm} disabled={templateDesignLoading}>
                    {templateDesignLoading ? "설계 중…" : "AI로 양식 설계"}
                  </button>
                  {templateSpec && (
                    <span className={`chip badge-inline${templateLlmUsed ? "" : " warn"}`}>
                      {templateLlmUsed ? "🧠 LLM이 설계함" : "⚙️ 휴리스틱 설계 (Azure 키 없음)"}
                    </span>
                  )}
                </div>
              </div>

              <div className="col">
                <div className="sub">
                  <div className="sub-label"><span className="step-chip">B</span> 설계된 컬럼 — 검토·수정 후 확정</div>
                  {!templateSpec && <p className="hint">왼쪽에서 설계를 실행하면 컬럼 표가 여기에 나타납니다. 확정 전까지 자유롭게 수정하세요.</p>}
                  {templateSpec && (
                    <>
                      <div className="table-wrap">
                        <table className="errtable">
                          <thead><tr><th>컬럼명</th><th>형식</th><th>필수</th><th>허용값(/)</th><th></th></tr></thead>
                          <tbody>
                            {templateSpec.columns.map((c, i) => (
                              <tr key={i}>
                                <td><input className="cell-in" value={c.name} onChange={(e) => updateColumn(i, { name: e.target.value })} /></td>
                                <td>
                                  <select value={c.dtype} onChange={(e) => updateColumn(i, { dtype: e.target.value })}>
                                    <option value="text">텍스트</option>
                                    <option value="date">날짜</option>
                                    <option value="number">숫자</option>
                                    <option value="code">코드값</option>
                                  </select>
                                </td>
                                <td style={{ textAlign: "center" }}>
                                  <input type="checkbox" checked={c.required} onChange={(e) => updateColumn(i, { required: e.target.checked })} />
                                </td>
                                <td>
                                  {c.dtype === "code" ? (
                                    <input className="cell-in" value={c.allowed_values.join("/")} placeholder="정상/지연/보류"
                                      onChange={(e) => updateColumn(i, { allowed_values: e.target.value.split("/").map((v) => v.trim()).filter(Boolean) })} />
                                  ) : (<span className="muted">-</span>)}
                                </td>
                                <td><button className="ghost inline mini" onClick={() => removeColumn(i)}>✕</button></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <button className="ghost inline" onClick={addColumn}>+ 컬럼 추가</button>
                      <button className="primary block-btn" onClick={buildForm} disabled={templateBuildLoading}>
                        {templateBuildLoading ? "생성 중…" : "이 양식으로 엑셀 생성 · 확정"}
                      </button>
                    </>
                  )}
                  {templateBuilt && (
                    <div className="dispatch">
                      <div className="row">
                        <a className="primary" href={templateBuilt.download}>⬇ 생성된 양식 엑셀</a>
                        <span className="chip badge-inline">{templateBuilt.filename}</span>
                      </div>
                      <div className="block">
                        <h4>이 양식이 곧 회신 검증 규칙 (라운드트립)</h4>
                        <p className="field-line"><b>필수</b> · {templateBuilt.validation_rule.required_columns.join(", ") || "-"}</p>
                        <p className="field-line"><b>날짜</b> · {templateBuilt.validation_rule.date_columns.join(", ") || "-"}</p>
                        <p className="field-line"><b>코드값</b> · {Object.entries(templateBuilt.validation_rule.code_rules).map(([k, v]) => `${k}=${v.join("/")}`).join(", ") || "-"}</p>
                      </div>
                      <label className="check-line">
                        <input type="checkbox" checked={useTemplateForFlow} onChange={(e) => setUseTemplateForFlow(e.target.checked)} />
                        이 양식을 아래 요청 발송·검증에 사용 (자동 첨부 + 검증 기준으로 고정)
                      </label>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===== 03 요청 ===== */}
        <section className="lane" style={{ order: 3 }}>
          <div className="lane-head">
            <div className="lane-eyebrow"><span className="lane-no">03</span><span className="lane-kicker">요청</span></div>
            <h2 className="lane-title">취합 요청 메일 보내기</h2>
            <p className="lane-desc">받은 요청 → 내 스타일 초안 → 양식 첨부·발송{templateBuilt && useTemplateForFlow ? " · 생성한 양식 자동 첨부됨" : ""}</p>
          </div>
          <div className="lane-body">
            <div className="split wide-left">
              <div className="col">
                <div className="sub">
                  <div className="sub-label"><span className="step-chip">A</span> 받은 취합 요청 내용</div>
                  <div className="row"><button className="ghost" onClick={loadSampleEmail}>내장 샘플 메일 불러오기</button></div>
                  <p className="hint">실제 Gmail 메일은 Claude Code가 Gmail MCP로 가져와 아래에 붙여넣습니다.</p>
                  <label>제목</label>
                  <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="예: 2026년 6월 시스템 개선 요청사항 취합" />
                  <label>본문 (직접 붙여넣기 가능)</label>
                  <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} placeholder="작성 항목, 마감일, 긴급도 기준 등을 포함한 본문" />
                </div>
                <div className="sub">
                  <div className="sub-label"><span className="step-chip">B</span> 내 발송 스타일 <span className="opt">선택 · {styleCount}개</span></div>
                  <label>내가 작성한 메일 파일 (.txt / .md / .eml)</label>
                  <input type="file" accept=".txt,.md,.eml" multiple onChange={uploadStyle} />
                  <label>또는 과거 메일 본문 붙여넣기</label>
                  <textarea value={styleInput} onChange={(e) => setStyleInput(e.target.value)} rows={2} placeholder="붙여넣고 저장하면 초안 톤에 반영됩니다." />
                  <button className="ghost inline" onClick={saveStylePaste}>붙여넣은 본문 저장</button>
                </div>
              </div>

              <div className="col">
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
                    <input value={draftSubject} onChange={(e) => setDraftSubject(e.target.value)} placeholder="초안 생성 시 자동 입력 / 직접 작성 가능" />
                    <label>메일 본문</label>
                    <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={8} placeholder="초안 생성 시 자동 입력 / 직접 작성 가능" />
                    <label>첨부 양식 엑셀 (요청과 함께 받은 양식)</label>
                    <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setAttachFiles(Array.from(e.target.files ?? []))} />
                    {attachFiles.length > 0 && (<ul className="filelist">{attachFiles.map((f) => (<li key={f.name}>📎 {f.name}</li>))}</ul>)}
                    <label>수신자 이메일 (쉼표로 여러 명)</label>
                    <input value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="hong@company.com, kim@company.com" />
                    <button className="primary inline" onClick={sendRequest} disabled={sendLoading}>{sendLoading ? "발송 중…" : "메일 보내기"}</button>
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
            </div>
          </div>
        </section>

        {/* ===== 04 검증 ===== */}
        <section className="lane" style={{ order: 4 }}>
          <div className="lane-head">
            <div className="lane-eyebrow"><span className="lane-no">04</span><span className="lane-kicker">검증</span></div>
            <h2 className="lane-title">제출 엑셀 검증 · 병합</h2>
            <p className="lane-desc">회신 첨부 검증 → 정상만 병합 → 취합 엑셀 다운로드</p>
          </div>
          <div className="lane-body">
            <div className="split">
              <div className="col">
                <div className="row">
                  <button className="ghost" onClick={makeSamples}>샘플 제출 엑셀 생성</button>
                  <button className="ghost" onClick={makeHardSamples}>하드 샘플 생성(오류 5종)</button>
                </div>
                <label>회신받은 제출 엑셀 업로드</label>
                <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
                {files.length > 0 && (<ul className="filelist">{files.map((f) => (<li key={f.name}>📄 {f.name}</li>))}</ul>)}
                <p className="hint">01 제목/본문이 비어 있으면 내장 샘플 메일을 자동으로 불러와 실행합니다. LLM 판단이 포함돼 약 8~12초 걸립니다.</p>
                <button className="primary block-btn" onClick={run} disabled={loading}>{loading ? "처리 중… (LLM 판단 포함, 최대 15초)" : "검증 · 병합 실행"}</button>
                {error && <p className="error inline-err">⚠ {error}</p>}
              </div>
              <div className="col">
                <div className="outbox">
                  <p className="outbox-title">검증 결과</p>
                  {result && vr ? (
                    <div className="result">
                      <div className="stats">
                        <Stat label="파일" value={vr.total_files} />
                        <Stat label="전체 행" value={vr.total_rows} />
                        <Stat label="정상" value={vr.valid_rows} tone="ok" />
                        <Stat label="오류" value={vr.error_rows} tone={vr.error_rows ? "bad" : "ok"} />
                      </div>
                      {result.validation_rules && (
                        <div className="block">
                          <h4>적용된 검증 규칙 {result.template_locked && <span className="chip badge-inline">🔒 생성한 양식 = 검증 계약</span>}</h4>
                          <p className="field-line"><b>필수</b> · {result.validation_rules.required_columns.join(", ") || "-"}</p>
                          <p className="field-line"><b>날짜</b> · {result.validation_rules.date_columns.join(", ") || "-"}</p>
                          <p className="field-line"><b>코드값</b> · {Object.entries(result.validation_rules.code_rules).map(([k, v]) => `${k}=${v.join("/")}`).join(", ") || "-"}</p>
                        </div>
                      )}
                      {vr.error_details.length > 0 && (
                        <div className="block">
                          <h4>오류 상세 ({vr.error_details.length})</h4>
                          <div className="table-wrap">
                            <table className="errtable">
                              <thead><tr><th>파일</th><th>행</th><th>컬럼</th><th>유형</th><th>값</th></tr></thead>
                              <tbody>
                                {vr.error_details.map((e, i) => (
                                  <tr key={i}><td>{e.file}</td><td>{e.row}</td><td>{e.column}</td><td><span className="etype">{e.error_type}</span></td><td>{e.value ?? "-"}</td></tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                      <div className="block downloads">
                        {result.downloads.merged && (<a className="primary" href={result.downloads.merged}>⬇ 취합 엑셀</a>)}
                        {result.downloads.error && (<a className="ghost" href={result.downloads.error}>⬇ 오류 보고서</a>)}
                        {result.downloads.trace_md && (<a className="ghost" href={result.downloads.trace_md}>⬇ 추론 트레이스(.md)</a>)}
                        {result.downloads.trace_json && (<a className="ghost" href={result.downloads.trace_json}>⬇ 트레이스(.json)</a>)}
                      </div>

                      {result.supervisor_plan && result.supervisor_plan.strategy && (
                        <div className="block plan-box">
                          <h4>🧠 Supervisor 판단 (LLM 계획)</h4>
                          <p className="field-line"><b>전략</b> · {result.supervisor_plan.strategy}
                            {result.supervisor_plan.source === "heuristic" && " (휴리스틱)"}</p>
                          {result.supervisor_plan.rationale && (
                            <p className="field-line"><b>근거</b> · {result.supervisor_plan.rationale}</p>
                          )}
                          {result.supervisor_plan.risks && result.supervisor_plan.risks.length > 0 && (
                            <p className="field-line"><b>사전 식별 리스크</b> · {result.supervisor_plan.risks.join(" / ")}</p>
                          )}
                        </div>
                      )}

                      {sc && sc.corrections.length > 0 && (
                        <div className="block">
                          <h4>자가교정 (LLM 제안 → 결정론 검증 → 채택)</h4>
                          <p className="field-line">
                            제안 {sc.applied_corrections}건 중 LLM {sc.corrections.filter((c) => c.source === "llm").length}건 ·
                            규칙 {sc.corrections.filter((c) => c.source === "rule").length}건 ·
                            재검증 오류 {sc.errors_before}→{sc.errors_after}행 {sc.accepted ? "(채택)" : "(기각)"}
                          </p>
                          <div className="table-wrap">
                            <table className="errtable">
                              <thead><tr><th>행</th><th>컬럼</th><th>교정</th><th>주체</th><th>LLM 근거</th></tr></thead>
                              <tbody>
                                {sc.corrections.map((c, i) => (
                                  <tr key={i}>
                                    <td>{c.row}</td><td>{c.column}</td>
                                    <td><code>{c.before}</code> → <code>{c.after}</code></td>
                                    <td><span className={`actor ${c.source === "llm" ? "actor-llm" : "actor-rule"}`}>{c.source === "llm" ? "LLM" : "규칙"}</span></td>
                                    <td>{c.rationale ?? "-"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      <div className="block">
                        <h4>에이전트 추론 타임라인 <span className="opt">· 시연·발표 증거</span></h4>
                        <ol className="trace">
                          {result.reasoning_steps.map((s) => (
                            <li className="trace-step" key={s.seq}>
                              <span className={`actor ${s.actor === "llm" ? "actor-llm" : "actor-rule"}`}>{s.actor === "llm" ? "🧠 LLM" : "⚙️ 규칙"}</span>
                              <span className="trace-phase">{s.phase}</span>
                              <span className="trace-decision">{s.decision}</span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    </div>
                  ) : (
                    <div className="placeholder">회신 엑셀을 업로드하고 ‘검증 · 병합 실행’을 누르면<br />통계 · 오류 상세 · 취합 엑셀 다운로드가 여기 표시됩니다.</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===== 03 추적 ===== */}
        <section className="lane" style={{ order: 5 }}>
          <div className="lane-head">
            <div className="lane-eyebrow"><span className="lane-no">05</span><span className="lane-kicker">추적</span></div>
            <h2 className="lane-title">제출 현황 · 리마인드</h2>
            <p className="lane-desc">제출 현황 확인 · 미제출자 리마인드 초안</p>
          </div>
          <div className="lane-body">
            <div className="split">
              <div className="col">
                <p className="hint">현재는 파일 식별자 기반 mock 추적입니다. 실제 회신 확인은 Gmail MCP로 수행할 수 있습니다(후속 확장).</p>
                <label>제출 식별자 (쉼표 구분)</label>
                <input value={submitted} onChange={(e) => setSubmitted(e.target.value)} />
                <label>마감일</label>
                <input value={deadline} onChange={(e) => setDeadline(e.target.value)} />
                <button className="primary block-btn" onClick={runTrack} disabled={trackLoading}>{trackLoading ? "확인 중…" : "제출 현황 확인 · 리마인드"}</button>
                {trackResult && (
                  <div className="block">
                    <p className="field-line"><b>{trackResult.summary}</b></p>
                    <div className="chips">{trackResult.missing_list.map((m) => (<span className="chip warn" key={m.email}>{m.dept} 미제출</span>))}</div>
                  </div>
                )}
              </div>
              <div className="col">
                <div className="dispatch">
                  <h4>보낼 리마인드 메일 — 수정·직접 작성 가능</h4>
                  <label>메일 제목</label>
                  <input value={reminderSubject} onChange={(e) => setReminderSubject(e.target.value)} placeholder="현황 확인 시 자동 입력 / 직접 작성 가능" />
                  <label>메일 본문</label>
                  <textarea value={reminderBody} onChange={(e) => setReminderBody(e.target.value)} rows={8} placeholder="현황 확인 시 자동 입력 / 직접 작성 가능" />
                  <label>첨부 파일 (선택)</label>
                  <input type="file" multiple onChange={(e) => setReminderAttach(Array.from(e.target.files ?? []))} />
                  {reminderAttach.length > 0 && (<ul className="filelist">{reminderAttach.map((f) => (<li key={f.name}>📎 {f.name}</li>))}</ul>)}
                  <label>수신자 이메일 (쉼표로 여러 명 · 미제출자 자동 입력)</label>
                  <input value={reminderRecipients} onChange={(e) => setReminderRecipients(e.target.value)} placeholder="미제출자 이메일이 자동 입력됩니다" />
                  <button className="primary inline" onClick={sendReminder} disabled={reminderSendLoading}>{reminderSendLoading ? "발송 중…" : "리마인드 메일 보내기"}</button>
                  {reminderSendResult && (
                    <p className="oktext">
                      {reminderSendResult.mode} · {reminderSendResult.status} · {reminderSendResult.message_id}
                      {reminderSendResult.attachments.length > 0 && ` · 첨부 ${reminderSendResult.attachments.length}개`}
                      {reminderSendResult.mode === "mock" && "  (mock 발송)"}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===== 04 수정 ===== */}
        <section className="lane" style={{ order: 6 }}>
          <div className="lane-head">
            <div className="lane-eyebrow"><span className="lane-no">06</span><span className="lane-kicker">수정</span></div>
            <h2 className="lane-title">공통 항목 일괄 수정</h2>
            <p className="lane-desc">기준 파일의 프로젝트 공통 정보로 대상 파일 동기화 (원본 보존)</p>
          </div>
          <div className="lane-body">
            <div className="split">
              <div className="col">
                <button className="ghost block-btn" onClick={makeProjectSamples}>프로젝트 샘플 5개 생성</button>
                {projectSampleInfo && <p className="hint">{projectSampleInfo}</p>}
                <label>기준 파일 업로드 (수정 완료된 최신 파일 1개)</label>
                <input type="file" accept=".xlsx,.xls" onChange={(e) => setReferenceFile(e.target.files?.[0] ?? null)} />
                {referenceFile && (<ul className="filelist"><li>📌 {referenceFile.name}</li></ul>)}
                <label>수정 대상 파일 업로드 (나머지 파일 여러 개)</label>
                <input type="file" accept=".xlsx,.xls" multiple onChange={(e) => setTargetFiles(Array.from(e.target.files ?? []))} />
                {targetFiles.length > 0 && (<ul className="filelist">{targetFiles.map((f) => (<li key={f.name}>📄 {f.name}</li>))}</ul>)}
                <p className="hint">프로젝트번호가 있으면 행별로 매칭하고, 없으면 기준 파일 첫 행의 공통 값을 적용합니다.</p>
                <button className="primary block-btn" onClick={runUpdateFields} disabled={updateLoading}>{updateLoading ? "동기화 중…" : "기준 파일 값으로 공통 항목 동기화"}</button>
              </div>
              <div className="col">
                <div className="outbox">
                  <p className="outbox-title">수정 결과</p>
                  {updateResult ? (
                    <div className="result">
                      <p className="field-line"><b>변경 셀 {updateResult.update_count}개</b> · 파일 {updateResult.downloads.length}개</p>
                      <p className="field-line"><b>기준 파일</b> · {updateResult.reference_file}</p>
                      <p className="field-line"><b>매칭 키</b> · {updateResult.key_column}</p>
                      <p className="field-line"><b>공통 컬럼</b> · {updateResult.common_columns.join(", ")}</p>
                      <div className="block downloads">
                        {updateResult.downloads.map((href, i) => (<a className="primary" href={href} key={href}>⬇ 수정 파일 {updateResult.downloads.length > 1 ? i + 1 : ""}</a>))}
                      </div>
                      {updateResult.details.some((d: any) => d.unmatched_keys?.length) && (
                        <div className="block">
                          <h4>매칭되지 않은 프로젝트번호</h4>
                          {updateResult.details.map((d: any) => d.unmatched_keys?.length ? (
                            <p className="field-line" key={d.file}>{d.file}: {d.unmatched_keys.join(", ")}</p>
                          ) : null)}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="placeholder">기준 파일 1개와 수정 대상 파일을 업로드하고 동기화를 누르면<br />공통 컬럼 변경 요약과 수정 파일 다운로드가 표시됩니다.</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ===== 05 수신함 자동 분류 ===== */}
        <section className="lane" style={{ order: 1 }}>
          <div className="lane-head">
            <div className="lane-eyebrow"><span className="lane-no">01</span><span className="lane-kicker">수신함</span></div>
            <h2 className="lane-title">수신함 자동 분류 · 요청 초안</h2>
            <p className="lane-desc">수신함 수집 → 취합요청/일반 분류(확신도) → 담당자별 요청 메일 초안 + 근거 검증 → 사람 승인 후 발송</p>
          </div>
          <div className="lane-body">
            <div className="split">
              <div className="col">
                <button className="primary block-btn" onClick={runInboxIngest} disabled={inboxLoading}>{inboxLoading ? "수집·분류 중… (LLM 판단 포함)" : "수신함 수집 · 분류"}</button>
                <p className="hint">실제 Gmail은 <code>EMAIL_READ_MODE=gmail</code> + credentials 설정 시 동작. 자동 발송하지 않고 사람이 승인합니다.</p>

                {/* 자동 수집 스케줄 */}
                <div className="sched">
                  <div className="sched-head">
                    <label className="sched-toggle">
                      <input type="checkbox" checked={schedEnabled} onChange={(e) => setSchedEnabled(e.target.checked)} />
                      <b>자동 수집 스케줄</b>
                    </label>
                    <span className={`sched-badge${schedEnabled ? " on" : ""}`}>{schedEnabled ? "켜짐" : "꺼짐"}</span>
                  </div>
                  <div className="sched-row">
                    <label>주기</label>
                    <select value={schedMode} onChange={(e) => setSchedMode(e.target.value as any)}>
                      <option value="times">매일 지정 시각</option>
                      <option value="interval">N시간마다</option>
                      <option value="weekly">매주</option>
                    </select>
                  </div>
                  {schedMode === "times" && (
                    <div className="sched-times">
                      {schedTimes.map((t, i) => (
                        <span className="sched-time" key={i}>
                          <input type="time" value={t} onChange={(e) => { const n = [...schedTimes]; n[i] = e.target.value; setSchedTimes(n); }} />
                          {schedTimes.length > 1 && <button className="tiny" onClick={() => setSchedTimes(schedTimes.filter((_, j) => j !== i))}>×</button>}
                        </span>
                      ))}
                      <button className="tiny add" onClick={() => setSchedTimes([...schedTimes, "12:00"])}>+ 시각</button>
                    </div>
                  )}
                  {schedMode === "interval" && (
                    <div className="sched-row">
                      <input type="number" min={1} max={168} value={schedInterval} onChange={(e) => setSchedInterval(Number(e.target.value))} style={{ width: 70 }} />
                      <span>시간마다</span>
                    </div>
                  )}
                  {schedMode === "weekly" && (
                    <div className="sched-row">
                      <select value={schedWeekday} onChange={(e) => setSchedWeekday(Number(e.target.value))}>
                        {["월", "화", "수", "목", "금", "토", "일"].map((d, i) => <option key={i} value={i}>{d}요일</option>)}
                      </select>
                      <input type="time" value={schedWeeklyTime} onChange={(e) => setSchedWeeklyTime(e.target.value)} />
                    </div>
                  )}
                  <div className="sched-actions">
                    <button className="primary" onClick={saveSchedule} disabled={schedSaving}>{schedSaving ? "저장 중…" : "스케줄 저장"}</button>
                    <button className="ghost" onClick={runScheduleNow} disabled={schedSaving}>지금 실행</button>
                  </div>
                  {sched && (
                    <div className="sched-info">
                      {sched.next_runs.length > 0 && <p className="hint">다음 실행: {sched.next_runs.slice(0, 3).join("  ·  ")}</p>}
                      {sched.last_run && <p className="hint">마지막 실행: {sched.last_run}{sched.last_summary ? ` · 신규 ${sched.last_summary.processed_new}건` : ""}</p>}
                      {sched.last_error && <p className="error inline-err">⚠ {sched.last_error}</p>}
                    </div>
                  )}
                </div>
                {inbox && (
                  <div className="stats">
                    <Stat label="수집" value={inbox.fetched} />
                    <Stat label="신규" value={inbox.processed_new} />
                    <Stat label="초안" value={inbox.by_status.draft_ready ?? 0} tone="ok" />
                    <Stat label="확인필요" value={inbox.by_status.needs_review ?? 0} tone={(inbox.by_status.needs_review ?? 0) ? "bad" : "ok"} />
                    <Stat label="자동/승인 발송" value={inbox.automation?.sent ?? inbox.by_status.sent ?? 0} tone="ok" />
                    <Stat label="격리" value={inbox.automation?.quarantined ?? inbox.by_status.quarantined ?? 0} tone={(inbox.by_status.quarantined ?? 0) ? "bad" : "ok"} />
                  </div>
                )}
                {collectionJobs.length > 0 && (
                  <div className="block">
                    <h4>Collection Job</h4>
                    <div className="inbox-queue">
                      {collectionJobs.slice(0, 5).map((job) => (
                        <div className="inbox-item" key={job.job_id}>
                          <div className="inbox-top">
                            <span className="ibadge cls">{job.job_id}</span>
                            <span className={`ibadge ${job.status === "completed" ? "ok" : "warn"}`}>{job.status}</span>
                          </div>
                          <p className="isubject">{job.title}</p>
                          <p className="field-line"><b>마감</b> · {job.deadline || "확인 필요"} · <b>대상</b> {job.recipients.length}명</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {inboxMsg && <p className="hint">✓ {inboxMsg}</p>}
                {error && <p className="error inline-err">⚠ {error}</p>}
              </div>
              <div className="col">
                <div className="outbox">
                  <p className="outbox-title">검토 큐</p>
                  {inbox ? (
                    <div className="result inbox-queue">
                      {inbox.queue.map((item) => {
                        const tierClass = item.status === "draft_ready" || item.status === "submission_accepted" ? "ok" : item.status === "needs_review" || item.status === "quarantined" ? "warn" : item.status === "sent" ? "sent" : "muted";
                        const label = { draft_ready: "승인 대기", submission_accepted: "제출 검증 통과", needs_review: "확인 필요", general: "일반", quarantined: "격리", sent: "자동/승인 발송", error: "오류" }[item.status] ?? item.status;
                        return (
                          <div className={`inbox-item ${tierClass}`} key={item.message_id}>
                            <div className="inbox-top">
                              <span className={`ibadge ${tierClass}`}>{label}</span>
                              <span className="ibadge cls">{item.classification} {Math.round(item.confidence * 100)}%</span>
                              {item.intent && item.intent !== "other" && <span className="ibadge cls">의도 {item.intent}</span>}
                              <span className="isender">{item.sender}</span>
                            </div>
                            <p className="isubject">{item.subject}</p>
                            {item.status === "draft_ready" && (
                              <div className="idraft">
                                <p className="field-line"><b>초안</b> · {item.draft_subject}</p>
                                <p className="field-line"><b>수신자</b> · {item.recipients.map((r) => r.email).join(", ")}</p>
                                <p className="field-line"><b>양식</b> · {item.artifacts?.strategy === "generate" ? "AI 신규 생성" : "첨부 양식 사용"} · {item.artifacts?.filename ?? "확인 필요"}</p>
                                <p className="field-line"><b>자율성 판단</b> · {item.decision?.action === "auto_send" ? "자동 발송" : "사람 승인"} · {item.decision?.source ?? "policy"}</p>
                                <p className="field-line">
                                  <b>근거</b> · {Math.round((item.grounding?.score ?? 0) * 100)}%
                                  {item.sources?.length ? ` · ${item.sources.slice(0, 2).join(", ")}` : ""}
                                </p>
                                {item.grounding?.flags?.length > 0 && (
                                  <p className="iflags">⚠ 확인 필요: {item.grounding.flags.join(", ")}</p>
                                )}
                                {!!item.artifacts?.agent_trace?.length && (
                                  <div className="plan-box">
                                    <b>Agent 실행 로그</b>
                                    <ul className="trace">
                                      {item.artifacts.agent_trace.slice(-6).map((step) => (
                                        <li className="trace-step" key={step.seq}>
                                          <span className="trace-phase">{step.agent}</span>
                                          <span className="actor actor-rule">{step.outcome}</span>
                                          <span className="trace-decision">{step.action}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                <button className="primary" onClick={() => approveSend(item.message_id)} disabled={sendingId === item.message_id}>
                                  {sendingId === item.message_id ? "발송 중…" : "승인 · 발송"}
                                </button>
                              </div>
                            )}
                            {item.status === "needs_review" && (
                              <p className="iflags">사람 확인 필요: {item.decision?.reasons?.join(" · ") || "분류 신뢰도 또는 업무 의도가 불명확합니다."}</p>
                            )}
                            {item.status === "quarantined" && <p className="iflags">자동 실행 차단: 스팸·피싱·프롬프트 인젝션 가능성이 있습니다.</p>}
                            {item.status === "sent" && item.decision?.action === "auto_send" && <p className="field-line"><b>자동 발송 완료</b> · 안전 정책 통과</p>}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="placeholder">‘수신함 수집·분류’를 누르면 분류 결과와<br />담당자별 요청 메일 초안, 근거 검증이 표시됩니다.</div>
                  )}
                </div>
              </div>
            </div>
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

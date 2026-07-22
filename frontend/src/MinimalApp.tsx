import { useEffect, useMemo, useState } from "react";
import {
  buildTemplate,
  collect,
  createGuide,
  designTemplate,
  genHardSamples,
  genProjectSamples,
  getAgentJobs,
  getHealth,
  getSampleEmail,
  getSchedule,
  getStyleMails,
  inboxQueue,
  inboxReset,
  inboxSend,
  saveStyleMail,
  scheduleRunNow,
  sendRequestMail,
  setSchedule,
  syncCommonFields,
  trackSubmissions,
  uploadStyleMails,
  type BuildTemplateResponse,
  type CollectionJob,
  type GuideResponse,
  type Health,
  type InboxItem,
  type IngestResult,
  type ScheduleStatus,
  type SendRequestMailResponse,
  type SyncCommonFieldsResponse,
  type TemplateSpec,
  type TrackResponse,
} from "./api";
import type { CollectResponse } from "./types";

type ViewMode = "operate" | "demo";
type DemoStep = "template" | "request" | "validate" | "track" | "sync";
type QueueFilter = "all" | "done" | "action" | "quarantine";

const DEMO_STEPS: Array<{ id: DemoStep; number: string; label: string; description: string }> = [
  { id: "template", number: "01", label: "양식 설계", description: "요청을 검증 가능한 엑셀로" },
  { id: "request", number: "02", label: "요청 발송", description: "작성 안내와 메일 초안 생성" },
  { id: "validate", number: "03", label: "검증·병합", description: "오류 탐지, 교정, 정상 건 병합" },
  { id: "track", number: "04", label: "제출 추적", description: "미제출자를 찾아 리마인드" },
  { id: "sync", number: "05", label: "기준 엑셀 업데이트", description: "같은 컬럼 값을 여러 파일에 일괄 반영" },
];

const STATUS_LABEL: Record<string, string> = {
  draft_ready: "승인 대기",
  needs_review: "확인 필요",
  general: "일반 메일",
  quarantined: "격리",
  sent: "발송 완료",
  error: "오류",
  submission_accepted: "제출 검증 통과",
};

const CLASS_LABEL: Record<string, string> = {
  collection_request: "취합요청",
  collection: "취합 업무",
  취합업무메일: "취합 업무",
  general: "일반",
  일반메일: "일반",
  spam: "스팸·위험",
  "스팸·위험메일": "스팸·위험",
};

function toMessage(error: unknown) {
  const value = error as { response?: { data?: { detail?: string } }; message?: string };
  return value?.response?.data?.detail ?? value?.message ?? String(error);
}

function initialMode(): ViewMode {
  return new URLSearchParams(window.location.search).get("view") === "demo" ? "demo" : "operate";
}

function initialStep(): DemoStep {
  const value = new URLSearchParams(window.location.search).get("step") as DemoStep | null;
  return DEMO_STEPS.some((step) => step.id === value) ? value! : "template";
}

function formatDateTime(value?: string | null) {
  if (!value) return "";
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export default function MinimalApp() {
  const [mode, setMode] = useState<ViewMode>(initialMode);
  const [demoStep, setDemoStep] = useState<DemoStep>(initialStep);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 자동 운영
  const [inbox, setInbox] = useState<IngestResult | null>(null);
  const [jobs, setJobs] = useState<CollectionJob[]>([]);
  const [schedule, setScheduleState] = useState<ScheduleStatus | null>(null);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleTimes, setScheduleTimes] = useState<string[]>(["09:00", "14:00", "19:00"]);
  const [operating, setOperating] = useState(false);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");

  // 양식 설계
  const [templateIntent, setTemplateIntent] = useState(
    "프로젝트별 월 실적을 취합합니다. 프로젝트번호, 담당자, 매출액, 진행상태(정상/지연/보류), 마감일자를 받고 싶어요."
  );
  const [templateSpec, setTemplateSpec] = useState<TemplateSpec | null>(null);
  const [templateBuilt, setTemplateBuilt] = useState<BuildTemplateResponse | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateLlmUsed, setTemplateLlmUsed] = useState(false);

  // 요청 메일
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [guide, setGuide] = useState<GuideResponse | null>(null);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [recipients, setRecipients] = useState("kimys@company.com, jung@company.com, ohsh@company.com");
  const [requestFiles, setRequestFiles] = useState<File[]>([]);
  const [requestLoading, setRequestLoading] = useState(false);
  const [requestSent, setRequestSent] = useState<SendRequestMailResponse | null>(null);
  const [styleCount, setStyleCount] = useState(0);
  const [styleText, setStyleText] = useState("");

  // 검증
  const [submissionFiles, setSubmissionFiles] = useState<File[]>([]);
  const [collectResult, setCollectResult] = useState<CollectResponse | null>(null);
  const [collectLoading, setCollectLoading] = useState(false);
  const [sampleHint, setSampleHint] = useState<string | null>(null);

  // 추적
  const [submitted, setSubmitted] = useState("영업팀, 생산팀, 품질팀");
  const [deadline, setDeadline] = useState("2026-06-12 17:00");
  const [trackResult, setTrackResult] = useState<TrackResponse | null>(null);
  const [trackLoading, setTrackLoading] = useState(false);
  const [reminderSubject, setReminderSubject] = useState("");
  const [reminderBody, setReminderBody] = useState("");
  const [reminderRecipients, setReminderRecipients] = useState("");
  const [reminderSent, setReminderSent] = useState<SendRequestMailResponse | null>(null);

  // 일괄 수정
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [targetFiles, setTargetFiles] = useState<File[]>([]);
  const [syncResult, setSyncResult] = useState<SyncCommonFieldsResponse | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncHint, setSyncHint] = useState<string | null>(null);

  useEffect(() => {
    void Promise.allSettled([getHealth(), getSchedule(), inboxQueue(), getAgentJobs(), getStyleMails()]).then(
      ([healthResult, scheduleResult, queueResult, jobsResult, styleResult]) => {
        if (healthResult.status === "fulfilled") setHealth(healthResult.value);
        if (scheduleResult.status === "fulfilled") applySchedule(scheduleResult.value);
        if (queueResult.status === "fulfilled") {
          setInbox({
            fetched: 0,
            processed_new: 0,
            skipped: 0,
            by_status: queueResult.value.counts,
            queue: queueResult.value.queue,
            read_mode: queueResult.value.read_mode,
          });
        }
        if (jobsResult.status === "fulfilled") setJobs(jobsResult.value.jobs);
        if (styleResult.status === "fulfilled") setStyleCount(styleResult.value.count);
      }
    );
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("view", mode);
    if (mode === "demo") params.set("step", demoStep);
    else params.delete("step");
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, [mode, demoStep]);

  function applySchedule(value: ScheduleStatus) {
    setScheduleState(value);
    setScheduleEnabled(value.config.enabled);
    setScheduleTimes(value.config.times?.length ? value.config.times : ["09:00"]);
  }

  function clearFeedback() {
    setError(null);
    setNotice(null);
  }

  async function refreshAutomation(summary?: ScheduleStatus["last_summary"]) {
    const [queue, agentJobs] = await Promise.all([inboxQueue(), getAgentJobs()]);
    setInbox({
      fetched: summary?.fetched ?? 0,
      processed_new: summary?.processed_new ?? 0,
      skipped: 0,
      by_status: queue.counts,
      queue: queue.queue,
      read_mode: queue.read_mode,
    });
    setJobs(agentJobs.jobs);
  }

  async function runNow() {
    clearFeedback();
    setOperating(true);
    try {
      const response = await scheduleRunNow();
      applySchedule(response.status);
      await refreshAutomation(response.status.last_summary);
      setNotice(`메일 확인 완료 · 신규 ${response.status.last_summary?.processed_new ?? 0}건`);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setOperating(false);
    }
  }

  async function resetDemo() {
    clearFeedback();
    setOperating(true);
    try {
      await inboxReset(false);
      await refreshAutomation();
      setMode("operate");
      setNotice("전부 초기화했습니다 (0). '지금 메일 확인'을 누르면 에이전트가 처리합니다.");
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setOperating(false);
    }
  }

  async function saveScheduleConfig() {
    clearFeedback();
    setSavingSchedule(true);
    try {
      const updated = await setSchedule({
        enabled: scheduleEnabled,
        mode: "times",
        times: scheduleTimes,
      });
      applySchedule(updated);
      setNotice("자동 확인 스케줄을 저장했습니다.");
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setSavingSchedule(false);
    }
  }

  async function approve(item: InboxItem, options: {
    extraRecipients?: string[];
    recipients?: string[];
    subject?: string;
    body?: string;
  } = {}) {
    clearFeedback();
    setSendingId(item.message_id);
    try {
      const response = await inboxSend(item.message_id, options);
      await refreshAutomation();
      setNotice(
        `${health?.email_send_mode === "mock" ? "Mock " : ""}${response.additional_only ? "추가 " : ""}발송을 완료했습니다.`
      );
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setSendingId(null);
    }
  }

  async function designForm() {
    clearFeedback();
    setTemplateLoading(true);
    setTemplateBuilt(null);
    try {
      const response = await designTemplate(templateIntent, true);
      setTemplateSpec(response.template_spec);
      setTemplateLlmUsed(response.llm_used);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setTemplateLoading(false);
    }
  }

  function updateColumn(index: number, patch: Partial<TemplateSpec["columns"][number]>) {
    setTemplateSpec((current) =>
      current
        ? { ...current, columns: current.columns.map((column, i) => (i === index ? { ...column, ...patch } : column)) }
        : current
    );
  }

  async function confirmTemplate() {
    if (!templateSpec) return;
    clearFeedback();
    setTemplateLoading(true);
    try {
      setTemplateBuilt(await buildTemplate(templateSpec));
      setNotice("검증 규칙이 포함된 취합 양식을 확정했습니다.");
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setTemplateLoading(false);
    }
  }

  async function loadSample() {
    clearFeedback();
    try {
      const sample = await getSampleEmail();
      setSubject(sample.subject);
      setBody(sample.body);
      setNotice("발표용 샘플 요청을 불러왔습니다.");
    } catch (e) {
      setError(toMessage(e));
    }
  }

  async function createDraft() {
    clearFeedback();
    setRequestLoading(true);
    setRequestSent(null);
    try {
      const response = await createGuide(subject, body);
      setGuide(response);
      setDraftSubject(response.mail_draft.mail_subject);
      setDraftBody(response.mail_draft.mail_body);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setRequestLoading(false);
    }
  }

  async function sendRequest() {
    clearFeedback();
    if (!draftSubject.trim() || !draftBody.trim() || !recipients.trim()) {
      setError("제목, 본문, 수신자를 확인해 주세요.");
      return;
    }
    setRequestLoading(true);
    try {
      const response = await sendRequestMail({
        to: recipients,
        subject: draftSubject,
        body: draftBody,
        files: requestFiles,
        templateId: templateBuilt?.template_id,
      });
      setRequestSent(response);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setRequestLoading(false);
    }
  }

  async function saveStyle() {
    if (!styleText.trim()) return;
    clearFeedback();
    try {
      const response = await saveStyleMail("발송 스타일 예시", styleText);
      setStyleCount(response.count);
      setStyleText("");
      setNotice("메일 작성 스타일을 저장했습니다.");
    } catch (e) {
      setError(toMessage(e));
    }
  }

  async function uploadStyle(files: File[]) {
    if (!files.length) return;
    clearFeedback();
    try {
      const response = await uploadStyleMails(files);
      setStyleCount(response.count);
      setNotice(`${response.saved.length}개의 스타일 예시를 저장했습니다.`);
    } catch (e) {
      setError(toMessage(e));
    }
  }

  async function makeHardSamples() {
    clearFeedback();
    try {
      const response = await genHardSamples();
      setSampleHint(`샘플 ${response.expected.total_files}개 생성 · 예상 오류 ${response.expected.error_rows}행`);
      setNotice("data/samples/hard 폴더에 발표용 샘플을 생성했습니다.");
    } catch (e) {
      setError(toMessage(e));
    }
  }

  async function validateAndMerge() {
    clearFeedback();
    if (!submissionFiles.length) {
      setError("검증할 엑셀 파일을 한 개 이상 선택해 주세요.");
      return;
    }
    setCollectLoading(true);
    setCollectResult(null);
    try {
      let requestSubject = subject;
      let requestBody = body;
      if (!requestSubject.trim() || !requestBody.trim()) {
        const sample = await getSampleEmail();
        requestSubject = sample.subject;
        requestBody = sample.body;
      }
      const response = await collect({
        subject: requestSubject,
        body: requestBody,
        useGraph: true,
        useLlm: true,
        files: submissionFiles,
        templateId: templateBuilt?.template_id,
      });
      setCollectResult(response);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setCollectLoading(false);
    }
  }

  async function runTracking() {
    clearFeedback();
    setTrackLoading(true);
    setTrackResult(null);
    try {
      const response = await trackSubmissions(
        submitted.split(",").map((value) => value.trim()).filter(Boolean),
        deadline
      );
      setTrackResult(response);
      setReminderSubject(response.reminder?.reminder_mail_subject ?? "");
      setReminderBody(response.reminder?.reminder_mail_body ?? "");
      setReminderRecipients(response.missing_list.map((item) => item.email).filter(Boolean).join(", "));
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setTrackLoading(false);
    }
  }

  async function sendReminder() {
    clearFeedback();
    if (!reminderRecipients || !reminderSubject || !reminderBody) {
      setError("리마인드 메일과 수신자를 먼저 확인해 주세요.");
      return;
    }
    setTrackLoading(true);
    try {
      setReminderSent(await sendRequestMail({
        to: reminderRecipients,
        subject: reminderSubject,
        body: reminderBody,
        files: [],
      }));
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setTrackLoading(false);
    }
  }

  async function makeSyncSamples() {
    clearFeedback();
    try {
      const response = await genProjectSamples();
      setSyncHint(`기준 파일 ${response.reference.split(/[\\/]/).pop()} · 대상 ${response.targets.length}개`);
      setNotice("data/samples/project_common 폴더에 샘플을 생성했습니다.");
    } catch (e) {
      setError(toMessage(e));
    }
  }

  async function syncFields() {
    clearFeedback();
    if (!referenceFile || !targetFiles.length) {
      setError("기준 파일과 수정 대상 파일을 선택해 주세요.");
      return;
    }
    setSyncLoading(true);
    setSyncResult(null);
    try {
      setSyncResult(await syncCommonFields({ referenceFile, targetFiles }));
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setSyncLoading(false);
    }
  }

  const visibleQueue = useMemo(() => {
    const queue = inbox?.queue ?? [];
    if (queueFilter === "done") return queue.filter((item) => ["sent", "general", "submission_accepted"].includes(item.status));
    if (queueFilter === "action") return queue.filter((item) => ["draft_ready", "needs_review", "error"].includes(item.status));
    if (queueFilter === "quarantine") return queue.filter((item) => item.status === "quarantined");
    return queue;
  }, [inbox, queueFilter]);

  const actionCount = (inbox?.queue ?? []).filter((item) => ["draft_ready", "needs_review"].includes(item.status)).length;
  const latestJob = jobs[0];

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">본문으로 바로가기</a>
      <header className="app-header">
        <a className="brand" href="#top" aria-label="Smart Collect 홈">
          <span className="brand-symbol">SC</span>
          <span>
            <strong>Smart Collect</strong>
            <small>AI collection agent</small>
          </span>
        </a>
        <div className="mode-switch" role="tablist" aria-label="화면 모드">
          <button
            className={mode === "operate" ? "active" : ""}
            onClick={() => setMode("operate")}
            role="tab"
            aria-selected={mode === "operate"}
          >
            자동 운영
          </button>
          <button
            className={mode === "demo" ? "active" : ""}
            onClick={() => setMode("demo")}
            role="tab"
            aria-selected={mode === "demo"}
          >
            단계별 시연
          </button>
        </div>
        <div className="header-right">
          <button
            className="reset-demo-btn"
            onClick={resetDemo}
            disabled={operating}
            title="검토 큐·취합 잡·로그를 전부 0으로 비웁니다. 이후 '지금 메일 확인'을 누르면 에이전트가 처리합니다 (연습용)"
          >
            {operating ? "초기화 중…" : "🔄 시연 초기화"}
          </button>
          <SystemStatus health={health} />
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        {error && (
          <div className="toast error-toast" role="alert">
            <span>확인이 필요합니다</span>
            <p>{error}</p>
            <button onClick={() => setError(null)} aria-label="오류 메시지 닫기">×</button>
          </div>
        )}
        {notice && (
          <div className="toast success-toast" role="status">
            <span>완료</span>
            <p>{notice}</p>
            <button onClick={() => setNotice(null)} aria-label="완료 메시지 닫기">×</button>
          </div>
        )}

        {mode === "operate" ? (
          <OperateView
            health={health}
            inbox={inbox}
            jobs={jobs}
            latestJob={latestJob}
            schedule={schedule}
            scheduleEnabled={scheduleEnabled}
            setScheduleEnabled={setScheduleEnabled}
            scheduleTimes={scheduleTimes}
            setScheduleTimes={setScheduleTimes}
            operating={operating}
            savingSchedule={savingSchedule}
            sendingId={sendingId}
            actionCount={actionCount}
            queueFilter={queueFilter}
            setQueueFilter={setQueueFilter}
            visibleQueue={visibleQueue}
            onRun={runNow}
            onSaveSchedule={saveScheduleConfig}
            onApprove={approve}
          />
        ) : (
          <DemoView activeStep={demoStep} setActiveStep={setDemoStep}>
            {demoStep === "template" && (
              <TemplateStep
                intent={templateIntent}
                setIntent={setTemplateIntent}
                spec={templateSpec}
                built={templateBuilt}
                loading={templateLoading}
                llmUsed={templateLlmUsed}
                onDesign={designForm}
                onConfirm={confirmTemplate}
                onUpdateColumn={updateColumn}
              />
            )}
            {demoStep === "request" && (
              <RequestStep
                subject={subject}
                setSubject={setSubject}
                body={body}
                setBody={setBody}
                guide={guide}
                draftSubject={draftSubject}
                setDraftSubject={setDraftSubject}
                draftBody={draftBody}
                setDraftBody={setDraftBody}
                recipients={recipients}
                setRecipients={setRecipients}
                files={requestFiles}
                setFiles={setRequestFiles}
                loading={requestLoading}
                sent={requestSent}
                templateBuilt={templateBuilt}
                styleCount={styleCount}
                styleText={styleText}
                setStyleText={setStyleText}
                onLoadSample={loadSample}
                onCreateDraft={createDraft}
                onSend={sendRequest}
                onSaveStyle={saveStyle}
                onUploadStyle={uploadStyle}
              />
            )}
            {demoStep === "validate" && (
              <ValidateStep
                files={submissionFiles}
                setFiles={setSubmissionFiles}
                result={collectResult}
                loading={collectLoading}
                sampleHint={sampleHint}
                templateBuilt={templateBuilt}
                onMakeSamples={makeHardSamples}
                onRun={validateAndMerge}
              />
            )}
            {demoStep === "track" && (
              <TrackStep
                submitted={submitted}
                setSubmitted={setSubmitted}
                deadline={deadline}
                setDeadline={setDeadline}
                result={trackResult}
                loading={trackLoading}
                reminderSubject={reminderSubject}
                setReminderSubject={setReminderSubject}
                reminderBody={reminderBody}
                setReminderBody={setReminderBody}
                reminderRecipients={reminderRecipients}
                setReminderRecipients={setReminderRecipients}
                sent={reminderSent}
                onRun={runTracking}
                onSend={sendReminder}
              />
            )}
            {demoStep === "sync" && (
              <SyncStep
                referenceFile={referenceFile}
                setReferenceFile={setReferenceFile}
                targetFiles={targetFiles}
                setTargetFiles={setTargetFiles}
                result={syncResult}
                loading={syncLoading}
                hint={syncHint}
                onMakeSamples={makeSyncSamples}
                onRun={syncFields}
              />
            )}
          </DemoView>
        )}
      </main>
    </div>
  );
}

function SystemStatus({ health }: { health: Health | null }) {
  const ready = health?.status === "ok";
  return (
    <div className="system-status" title="시스템 연결 상태">
      <span className={`status-dot ${ready ? "online" : ""}`} />
      <span>{ready ? "시스템 정상" : "연결 확인 중…"}</span>
      {health && <em>{health.email_send_mode === "mock" ? "안전 모드" : "실메일"}</em>}
      {health && <em>{health.auto_send_enabled ? "자동완료 ON" : "승인 발송"}</em>}
    </div>
  );
}

interface OperateViewProps {
  health: Health | null;
  inbox: IngestResult | null;
  jobs: CollectionJob[];
  latestJob?: CollectionJob;
  schedule: ScheduleStatus | null;
  scheduleEnabled: boolean;
  setScheduleEnabled: (value: boolean) => void;
  scheduleTimes: string[];
  setScheduleTimes: (value: string[]) => void;
  operating: boolean;
  savingSchedule: boolean;
  sendingId: string | null;
  actionCount: number;
  queueFilter: QueueFilter;
  setQueueFilter: (value: QueueFilter) => void;
  visibleQueue: InboxItem[];
  onRun: () => void;
  onSaveSchedule: () => void;
  onApprove: (item: InboxItem, options?: {
    extraRecipients?: string[];
    recipients?: string[];
    subject?: string;
    body?: string;
  }) => void;
}

function OperateView(props: OperateViewProps) {
  const {
    health,
    inbox,
    latestJob,
    schedule,
    scheduleEnabled,
    setScheduleEnabled,
    scheduleTimes,
    setScheduleTimes,
    operating,
    savingSchedule,
    sendingId,
    actionCount,
    queueFilter,
    setQueueFilter,
    visibleQueue,
    onRun,
    onSaveSchedule,
    onApprove,
  } = props;
  const nextRun = formatDateTime(schedule?.next_runs?.[0]);

  return (
    <div className="operate-view page-enter">
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="eyebrow">AUTONOMOUS INBOX</span>
          <h1>메일이 오면,<br />에이전트가 먼저 처리합니다.</h1>
          <p>분류부터 양식 결정, 요청 초안, 제출 검증까지. 위험하거나 애매한 일만 사람에게 묻습니다.</p>
          <div className="hero-actions">
            <button className="button primary-button large" onClick={onRun} disabled={operating}>
              {operating ? <><Spinner /> 메일 확인 중…</> : "지금 메일 확인"}
            </button>
            <span className="safety-note">
              <span className="status-dot online" />
              {health?.email_send_mode === "mock"
                ? `${health.auto_send_enabled ? "자동완료 ON · " : ""}Mock 발송 · 실제 전송 없음`
                : health?.auto_send_enabled ? "안전 조건 충족 시 자동 발송" : "발송 전 승인 필요"}
            </span>
          </div>
        </div>
        <div className="decision-visual" aria-label="에이전트 처리 흐름">
          <div className="decision-source">
            <span>수신 메일</span>
            <strong>{inbox?.fetched ?? 0}</strong>
          </div>
          <span className="flow-line" />
          <div className="decision-core">
            <span className="pulse" />
            <small>LLM SUPERVISOR</small>
            <strong>판단 · 라우팅</strong>
          </div>
          <div className="decision-branches">
            <span><i className="branch-dot green" />자동 처리</span>
            <span><i className="branch-dot amber" />사람 확인</span>
            <span><i className="branch-dot red" />격리</span>
          </div>
        </div>
      </section>

      <section className="metric-strip" aria-label="처리 현황">
        <Metric label="신규 처리" value={inbox?.processed_new ?? 0} detail="이번 실행" />
        <Metric label="확인 필요" value={actionCount} detail="사람의 판단" accent={actionCount > 0} />
        <Metric label="자동 완료" value={(inbox?.by_status.sent ?? 0) + (inbox?.by_status.submission_accepted ?? 0)} detail="개입 없이" />
        <Metric label="격리" value={inbox?.by_status.quarantined ?? 0} detail="위험 차단" danger={(inbox?.by_status.quarantined ?? 0) > 0} />
      </section>

      <div className="operate-grid">
        <section className="panel queue-panel">
          <div className="panel-header">
            <div>
              <span className="eyebrow">REVIEW QUEUE</span>
              <h2>검토할 메일</h2>
            </div>
            <div className="filter-group" role="group" aria-label="메일 필터">
              {(["all", "done", "action", "quarantine"] as const).map((filter) => (
                <button key={filter} className={queueFilter === filter ? "active" : ""} onClick={() => setQueueFilter(filter)}>
                  {{ all: "전체", done: "처리 완료", action: "확인 필요", quarantine: "격리" }[filter]}
                </button>
              ))}
            </div>
          </div>
          <div className="queue-list">
            {visibleQueue.length ? visibleQueue.map((item) => (
              <QueueCard key={item.message_id} item={item} sending={sendingId === item.message_id} onApprove={onApprove} />
            )) : (
              <EmptyState title="지금 확인할 메일이 없습니다" description="새 메일이 도착하면 이곳에 판단 결과가 나타납니다." />
            )}
          </div>
        </section>

        <aside className="side-stack">
          <section className="panel schedule-panel">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">SCHEDULE</span>
                <h2>자동 확인</h2>
              </div>
              <label className="switch">
                <input name="schedule-enabled" type="checkbox" checked={scheduleEnabled} onChange={(e) => setScheduleEnabled(e.target.checked)} />
                <span />
                <b>{scheduleEnabled ? "켜짐" : "꺼짐"}</b>
              </label>
            </div>
            <p className="panel-description">매일 지정한 시간에 Gmail을 확인합니다.</p>
            <div className="time-list">
              {scheduleTimes.map((time, index) => (
                <div className="time-field" key={`${index}-${time}`}>
                  <input
                    type="time"
                    name={`schedule-time-${index}`}
                    aria-label={`${index + 1}번째 자동 확인 시각`}
                    value={time}
                    onChange={(e) => setScheduleTimes(scheduleTimes.map((value, i) => i === index ? e.target.value : value))}
                  />
                  {scheduleTimes.length > 1 && (
                    <button className="icon-button" onClick={() => setScheduleTimes(scheduleTimes.filter((_, i) => i !== index))} aria-label={`${time} 삭제`}>×</button>
                  )}
                </div>
              ))}
              <button className="text-button" onClick={() => setScheduleTimes([...scheduleTimes, "12:00"])}>+ 시간 추가</button>
            </div>
            <button className="button secondary-button full" onClick={onSaveSchedule} disabled={savingSchedule}>
              {savingSchedule ? "저장 중…" : "스케줄 저장"}
            </button>
            {nextRun && <p className="next-run">다음 실행 <strong>{nextRun}</strong></p>}
          </section>

          <section className="panel job-panel">
            <div className="panel-header compact">
              <div>
                <span className="eyebrow">ACTIVE JOB</span>
                <h2>최근 취합 업무</h2>
              </div>
            </div>
            {latestJob ? (
              <div className="job-summary">
                <StatusBadge status={latestJob.status === "completed" ? "sent" : "draft_ready"} />
                <h3>{latestJob.title}</h3>
                <dl>
                  <div><dt>대상</dt><dd>{latestJob.recipients.length}명</dd></div>
                  <div><dt>마감</dt><dd>{latestJob.deadline || "확인 필요"}</dd></div>
                  <div><dt>항목</dt><dd>{latestJob.required_fields.length}개</dd></div>
                </dl>
              </div>
            ) : <EmptyState title="진행 중인 업무 없음" description="취합요청 메일이 확인되면 자동으로 생성됩니다." compact />}
          </section>
        </aside>
      </div>
    </div>
  );
}

function QueueCard({ item, sending, onApprove }: {
  item: InboxItem;
  sending: boolean;
  onApprove: (item: InboxItem, options?: {
    extraRecipients?: string[];
    recipients?: string[];
    subject?: string;
    body?: string;
  }) => void;
}) {
  const [extraRecipients, setExtraRecipients] = useState("");
  const [draftRecipients, setDraftRecipients] = useState(
    () => item.recipients?.map((recipient) => recipient.email).join(", ") ?? ""
  );
  const [draftSubject, setDraftSubject] = useState(item.draft_subject ?? "");
  const [draftBody, setDraftBody] = useState(item.draft_body ?? "");
  const status = item.status;
  const confidence = Math.round(item.confidence * 100);
  const action = item.decision?.action;
  const isQuestion = item.intent === "question";
  const isCompletion = item.intent === "completion";
  const attachmentPathName = item.artifacts?.attachment_paths?.[0]?.split(/[\\/]/).pop();
  const displayedAttachment = item.artifacts?.filename
    || item.artifacts?.source_attachments?.[0]
    || attachmentPathName;
  const attachmentLabel = isCompletion
    ? "최종 취합본"
    : item.artifacts?.strategy === "generate"
      ? "새로 생성한 양식"
      : item.artifacts?.strategy === "review"
        ? "양식 상태"
        : item.artifacts?.source_attachments?.length
          ? "받은 첨부파일"
          : "첨부파일";
  const extras = extraRecipients.split(",").map((value) => value.trim()).filter(Boolean);
  const editedRecipients = draftRecipients.split(",").map((value) => value.trim()).filter(Boolean);
  const canSend = status === "draft_ready" || status === "sent";
  const recipientSource = item.artifacts?.recipient_source === "original_sender_cc"
    ? "원본 작성자·참조자"
    : item.artifacts?.recipient_source === "directory_explicit_target"
      ? "메일에 명시된 대상"
      : item.artifacts?.recipient_source === "question_sender"
        ? "질문 보낸 사람"
      : item.artifacts?.recipient_source === "original_requester_cc"
        ? "최초 요청자·참조자"
      : "확인 필요";
  const draftKind = isCompletion
    ? "최종 취합 결과 회신"
    : isQuestion
    ? "취합 문의 답변"
    : item.artifacts?.strategy === "generate" ? "새 양식 생성" : "첨부 양식 사용";
  return (
    <article className={`queue-card status-${status}`}>
      <div className="queue-card-top">
        <div className="badge-row">
          <StatusBadge status={status} />
          <span className="plain-badge">{CLASS_LABEL[item.classification] ?? item.classification} {confidence}%</span>
          {item.intent && item.intent !== "other" && <span className="plain-badge">{item.intent}</span>}
        </div>
        <time dateTime={item.received_at}>{formatDateTime(item.received_at)}</time>
      </div>
      <h3>{item.subject}</h3>
      <p className="sender">{item.sender}</p>

      {item.reasons?.length > 0 && (
        <p className="reason-box why"><b>판단 사유</b> · {item.reasons.join(" · ")}</p>
      )}
      {item.body && (
        <details className="disclosure original-mail" open={status === "needs_review"}>
          <summary>받은 원본 메일{status === "needs_review" ? "" : " 보기"}</summary>
          <pre>{item.body}</pre>
        </details>
      )}

      {status === "draft_ready" && (
        <div className="draft-summary">
          <div>
            <span>에이전트 결정</span>
            <strong>{draftKind} · {action === "auto_send" ? "자동 발송" : "승인 후 발송"}</strong>
          </div>
          <div>
            <span>{isQuestion ? "답변 근거" : "작성 근거"}</span>
            <strong>{isQuestion
              ? `${item.artifacts?.answer_grounding?.used_fact_keys?.length ?? 0}개 Job 사실`
              : `${Math.round((item.grounding?.score ?? 0) * 100)}% 검증`}</strong>
          </div>
        </div>
      )}

      {status === "needs_review" && (
        <p className="reason-box">{item.decision?.reasons?.join(" · ") || item.reasons?.join(" · ") || "업무 의도가 불명확해 사람의 확인이 필요합니다."}</p>
      )}
      {status === "quarantined" && <p className="reason-box danger">스팸, 위험 명령 또는 프롬프트 인젝션 가능성을 탐지해 실행을 차단했습니다.</p>}
      {status === "submission_accepted" && <p className="reason-box success">제출 파일의 구조와 값을 검증했습니다. 정상 데이터로 반영할 수 있습니다.</p>}
      {status === "sent" && isQuestion && <p className="reason-box success">저장된 취합 Job 근거로 질문자에게 자동 답변했습니다.</p>}
      {status === "sent" && isCompletion && <p className="reason-box success">최종 검증을 통과한 취합본을 최초 요청자에게 회신했습니다.</p>}

      {canSend && (
        <div className="recipient-box">
          <div className="recipient-heading">
            <span>발송 대상</span>
            <small>{recipientSource}</small>
          </div>
          {status === "draft_ready" ? (
            <>
              <label htmlFor={`recipients-${item.message_id}`}>수신자 · 쉼표로 구분해 추가·삭제·교체 가능</label>
              <input
                id={`recipients-${item.message_id}`}
                inputMode="email"
                autoComplete="off"
                spellCheck={false}
                value={draftRecipients}
                onChange={(event) => setDraftRecipients(event.target.value)}
              />
              <label htmlFor={`subject-${item.message_id}`}>메일 제목</label>
              <input
                id={`subject-${item.message_id}`}
                value={draftSubject}
                onChange={(event) => setDraftSubject(event.target.value)}
              />
              <label htmlFor={`body-${item.message_id}`}>메일 본문</label>
              <textarea
                id={`body-${item.message_id}`}
                rows={8}
                value={draftBody}
                onChange={(event) => setDraftBody(event.target.value)}
              />
            </>
          ) : (
            <div className="recipient-chips">
              {item.recipients?.length
                ? item.recipients.map((recipient) => <span key={recipient.email}>{recipient.name || recipient.email}<small>{recipient.email}</small></span>)
                : <em>기본 수신자가 없습니다.</em>}
            </div>
          )}
          <div className="recipient-add">
            <label htmlFor={`extra-${item.message_id}`}>{status === "sent" ? "추가로 다시 보낼 사람" : ""}</label>
            <div>
              {status === "sent" && <input
                  id={`extra-${item.message_id}`}
                  name={`extra-recipients-${item.message_id}`}
                  inputMode="email"
                  autoComplete="off"
                  spellCheck={false}
                  value={extraRecipients}
                  onChange={(event) => setExtraRecipients(event.target.value)}
                  placeholder="email@company.com…"
                />}
              <button
                className={`button ${status === "draft_ready" ? "primary-button" : "secondary-button"}`}
                onClick={() => onApprove(item, status === "sent"
                  ? { extraRecipients: extras }
                  : { recipients: editedRecipients, subject: draftSubject, body: draftBody })}
                disabled={sending || (status === "sent" ? extras.length === 0 : !editedRecipients.length || !draftSubject.trim() || !draftBody.trim())}
              >
                {sending ? "발송 중…" : status === "sent" ? "추가 발송" : "확인 후 발송"}
              </button>
            </div>
          </div>
        </div>
      )}

      {!isQuestion && displayedAttachment && (
        <div className="attachment-line">
          <span>{attachmentLabel}</span>
          <strong>{displayedAttachment}</strong>
          {item.artifacts?.download && <a href={item.artifacts.download}>양식 확인</a>}
        </div>
      )}

      {(item.draft_body || item.artifacts?.agent_trace?.length) && (
        <details className="disclosure">
          <summary>판단 근거와 실행 로그</summary>
          {item.draft_body && <pre>{item.draft_body}</pre>}
          {!!item.artifacts?.agent_trace?.length && (
            <ol className="trace-list">
              {item.artifacts.agent_trace.slice(-6).map((step) => (
                <li key={step.seq}><span>{step.agent}</span><strong>{step.action}</strong><em>{step.outcome}</em></li>
              ))}
            </ol>
          )}
        </details>
      )}
    </article>
  );
}

function DemoView({ activeStep, setActiveStep, children }: { activeStep: DemoStep; setActiveStep: (step: DemoStep) => void; children: React.ReactNode }) {
  const current = DEMO_STEPS.find((step) => step.id === activeStep)!;
  return (
    <div className="demo-view page-enter">
      <section className="demo-heading">
        <div>
          <span className="eyebrow">GUIDED DEMO</span>
          <h1>한 단계씩 확인하세요.</h1>
          <p>발표에서는 01부터 04까지만 진행하면 전체 에이전트 흐름을 보여줄 수 있습니다.</p>
        </div>
        <div className="demo-progress" aria-label={`현재 ${current.number} ${current.label}`}>
          <strong>{current.number}</strong>
          <span>{current.label}<small>{current.description}</small></span>
        </div>
      </section>
      <nav className="step-navigation" aria-label="시연 단계">
        {DEMO_STEPS.map((step) => (
          <button key={step.id} className={step.id === activeStep ? "active" : ""} onClick={() => setActiveStep(step.id)}>
            <span>{step.number}</span>
            <strong>{step.label}</strong>
            <small>{step.description}</small>
          </button>
        ))}
      </nav>
      <section className="demo-canvas" key={activeStep}>{children}</section>
    </div>
  );
}

interface TemplateStepProps {
  intent: string;
  setIntent: (value: string) => void;
  spec: TemplateSpec | null;
  built: BuildTemplateResponse | null;
  loading: boolean;
  llmUsed: boolean;
  onDesign: () => void;
  onConfirm: () => void;
  onUpdateColumn: (index: number, patch: Partial<TemplateSpec["columns"][number]>) => void;
}

function TemplateStep(props: TemplateStepProps) {
  const { intent, setIntent, spec, built, loading, llmUsed, onDesign, onConfirm, onUpdateColumn } = props;
  return (
    <div className="step-layout">
      <div className="step-form">
        <StepIntro number="01" title="원하는 취합 내용을 말해 주세요" description="LLM이 업무 문장을 컬럼, 데이터 형식, 필수값, 허용값으로 변환합니다." />
        <Field label="취합 업무 설명" hint="보기 값은 진행상태(정상/지연/보류)처럼 작성하세요.">
          <textarea name="template-intent" autoComplete="off" rows={7} value={intent} onChange={(e) => setIntent(e.target.value)} />
        </Field>
        <button className="button primary-button full" onClick={onDesign} disabled={loading || !intent.trim()}>
          {loading && !spec ? <><Spinner /> AI가 설계 중…</> : "AI로 양식 설계"}
        </button>
      </div>
      <div className="step-result">
        <ResultHeader title="설계 결과" meta={spec ? (llmUsed ? "LLM 설계" : "규칙 기반 대체") : "실행 전"} />
        {!spec ? <EmptyState title="아직 설계하지 않았습니다" description="왼쪽의 업무 설명을 확인하고 설계를 실행하세요." /> : (
          <>
            <div className="column-editor">
              <div className="column-head"><span>컬럼명</span><span>형식</span><span>필수</span><span>허용값</span></div>
              {spec.columns.map((column, index) => (
                <div className="column-row" key={`${column.name}-${index}`}>
                  <input name={`column-name-${index}`} autoComplete="off" aria-label={`${index + 1}번째 컬럼명`} value={column.name} onChange={(e) => onUpdateColumn(index, { name: e.target.value })} />
                  <select name={`column-type-${index}`} aria-label={`${column.name} 데이터 형식`} value={column.dtype} onChange={(e) => onUpdateColumn(index, { dtype: e.target.value })}>
                    <option value="text">텍스트</option><option value="date">날짜</option><option value="number">숫자</option><option value="code">선택값</option>
                  </select>
                  <input name={`column-required-${index}`} aria-label={`${column.name} 필수 여부`} type="checkbox" checked={column.required} onChange={(e) => onUpdateColumn(index, { required: e.target.checked })} />
                  <input name={`column-values-${index}`} autoComplete="off" aria-label={`${column.name} 허용값`} disabled={column.dtype !== "code"} value={column.allowed_values.join("/")} placeholder="정상/지연…" onChange={(e) => onUpdateColumn(index, { allowed_values: e.target.value.split("/").map((value) => value.trim()).filter(Boolean) })} />
                </div>
              ))}
            </div>
            <button className="button primary-button full" onClick={onConfirm} disabled={loading}>{loading ? "양식 생성 중…" : "이 설계로 양식 확정"}</button>
            {built && (
              <div className="success-card">
                <span>양식 생성 완료</span>
                <strong>{built.filename}</strong>
                <a className="button secondary-button" href={built.download}>엑셀 다운로드</a>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

interface RequestStepProps {
  subject: string; setSubject: (value: string) => void;
  body: string; setBody: (value: string) => void;
  guide: GuideResponse | null;
  draftSubject: string; setDraftSubject: (value: string) => void;
  draftBody: string; setDraftBody: (value: string) => void;
  recipients: string; setRecipients: (value: string) => void;
  files: File[]; setFiles: (files: File[]) => void;
  loading: boolean; sent: SendRequestMailResponse | null;
  templateBuilt: BuildTemplateResponse | null;
  styleCount: number; styleText: string; setStyleText: (value: string) => void;
  onLoadSample: () => void; onCreateDraft: () => void; onSend: () => void;
  onSaveStyle: () => void; onUploadStyle: (files: File[]) => void;
}

function RequestStep(props: RequestStepProps) {
  return (
    <div className="step-layout">
      <div className="step-form">
        <StepIntro number="02" title="요청 내용을 넣어 주세요" description="필수 항목과 마감일을 추출해 수신자가 이해하기 쉬운 작성 안내로 바꿉니다." />
        <button className="text-button sample-button" onClick={props.onLoadSample}>발표용 샘플 불러오기</button>
        <Field label="받은 메일 제목"><input name="request-subject" autoComplete="off" value={props.subject} onChange={(e) => props.setSubject(e.target.value)} /></Field>
        <Field label="받은 메일 본문"><textarea name="request-body" autoComplete="off" rows={6} value={props.body} onChange={(e) => props.setBody(e.target.value)} /></Field>
        <button className="button primary-button full" onClick={props.onCreateDraft} disabled={props.loading || !props.subject.trim() || !props.body.trim()}>
          {props.loading && !props.guide ? <><Spinner /> 초안 생성 중…</> : "요청 메일 초안 만들기"}
        </button>
        <details className="advanced-settings">
          <summary>내 메일 말투 학습 <span>{props.styleCount}개 저장됨</span></summary>
          <Field label="과거 메일 본문"><textarea name="style-example" autoComplete="off" rows={3} value={props.styleText} onChange={(e) => props.setStyleText(e.target.value)} /></Field>
          <div className="inline-actions">
            <button className="button secondary-button" onClick={props.onSaveStyle}>본문 저장</button>
            <label className="button secondary-button file-button">파일 추가<input name="style-files" type="file" accept=".txt,.md,.eml" multiple onChange={(e) => props.onUploadStyle(Array.from(e.target.files ?? []))} /></label>
          </div>
        </details>
      </div>
      <div className="step-result">
        <ResultHeader title="보낼 메일" meta={props.guide ? `${props.guide.llm_used ? "LLM" : "규칙"} · ${props.guide.style_used ? "내 말투 반영" : "기본 말투"}` : "초안 없음"} />
        {!props.guide ? <EmptyState title="초안이 여기에 나타납니다" description="샘플을 불러오면 빠르게 시연할 수 있습니다." /> : (
          <>
            <Field label="제목"><input name="draft-subject" autoComplete="off" value={props.draftSubject} onChange={(e) => props.setDraftSubject(e.target.value)} /></Field>
            <Field label="본문"><textarea name="draft-body" autoComplete="off" rows={10} value={props.draftBody} onChange={(e) => props.setDraftBody(e.target.value)} /></Field>
            <Field label="수신자" hint="쉼표로 여러 명을 입력할 수 있습니다."><input name="request-recipients" inputMode="email" autoComplete="off" spellCheck={false} value={props.recipients} onChange={(e) => props.setRecipients(e.target.value)} /></Field>
            <Field label="첨부 양식" hint={props.templateBuilt ? `${props.templateBuilt.filename} 자동 첨부 예정` : "필요하면 엑셀 파일을 선택하세요."}>
              <input name="request-attachments" type="file" accept=".xlsx,.xls" multiple onChange={(e) => props.setFiles(Array.from(e.target.files ?? []))} />
            </Field>
            <button className="button primary-button full" onClick={props.onSend} disabled={props.loading}>메일 보내기</button>
            {props.sent && <SentCard result={props.sent} />}
          </>
        )}
      </div>
    </div>
  );
}

function ValidateStep({ files, setFiles, result, loading, sampleHint, templateBuilt, onMakeSamples, onRun }: {
  files: File[]; setFiles: (files: File[]) => void; result: CollectResponse | null; loading: boolean; sampleHint: string | null;
  templateBuilt: BuildTemplateResponse | null; onMakeSamples: () => void; onRun: () => void;
}) {
  const validation = result?.validation_result;
  const correction = result?.self_correction;
  return (
    <div className="step-layout">
      <div className="step-form">
        <StepIntro number="03" title="회신받은 파일을 올려 주세요" description="여러 파일을 동시에 검사하고, 교정 가능한 오류는 고친 뒤 정상 행만 병합합니다." />
        <button className="text-button sample-button" onClick={onMakeSamples}>오류 5종 발표용 샘플 생성</button>
        {sampleHint && <p className="inline-note">{sampleHint}</p>}
        <Field label="제출 엑셀" hint="data/samples/hard 폴더의 파일 3개를 한 번에 선택하세요.">
          <input name="submission-files" type="file" accept=".xlsx,.xls" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </Field>
        <FileSummary files={files} />
        {templateBuilt && <p className="inline-note success">검증 기준 · {templateBuilt.filename}</p>}
        <button className="button primary-button full" onClick={onRun} disabled={loading || !files.length}>
          {loading ? <><Spinner /> 멀티에이전트 검증 중…</> : "검증하고 병합하기"}
        </button>
      </div>
      <div className="step-result">
        <ResultHeader title="검증 결과" meta={result ? "처리 완료" : "실행 전"} />
        {!result || !validation ? <EmptyState title="검증 결과가 여기에 나타납니다" description="오류 수, 자동 교정률, 병합 파일을 한 화면에서 확인합니다." /> : (
          <>
            <div className="result-metrics">
              <Metric label="전체 행" value={validation.total_rows} detail={`${validation.total_files}개 파일`} />
              <Metric label="정상 행" value={validation.valid_rows} detail="병합 대상" />
              <Metric label="오류 행" value={validation.error_rows} detail={`${validation.error_types.length}개 유형`} danger={validation.error_rows > 0} />
              <Metric label="자동 교정" value={`${Math.round((correction?.auto_fix_rate ?? 0) * 100)}%`} detail={`${correction?.applied_corrections ?? 0}건`} />
            </div>
            <div className="download-row">
              {result.downloads.merged && <a className="button primary-button" href={result.downloads.merged}>병합 엑셀 다운로드</a>}
              {result.downloads.error && <a className="button secondary-button" href={result.downloads.error}>오류 보고서</a>}
              {result.downloads.trace_md && <a className="button secondary-button" href={result.downloads.trace_md}>Agent 로그</a>}
            </div>
            {validation.error_details.length > 0 && (
              <details className="disclosure" open>
                <summary>오류 상세 {validation.error_details.length}건</summary>
                <div className="simple-table">
                  {validation.error_details.slice(0, 8).map((item, index) => (
                    <div key={`${item.file}-${item.row}-${index}`}><span>{item.file}</span><strong>{item.row}행 · {item.column || "-"}</strong><em>{item.error_type}</em></div>
                  ))}
                </div>
              </details>
            )}
            {!!result.reasoning_steps.length && (
              <details className="disclosure">
                <summary>멀티에이전트 실행 과정</summary>
                <ol className="trace-list">
                  {result.reasoning_steps.slice(-8).map((step) => <li key={step.seq}><span>{step.agent}</span><strong>{step.decision}</strong><em>{step.actor}</em></li>)}
                </ol>
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function TrackStep(props: {
  submitted: string; setSubmitted: (value: string) => void; deadline: string; setDeadline: (value: string) => void;
  result: TrackResponse | null; loading: boolean; reminderSubject: string; setReminderSubject: (value: string) => void;
  reminderBody: string; setReminderBody: (value: string) => void; reminderRecipients: string; setReminderRecipients: (value: string) => void;
  sent: SendRequestMailResponse | null; onRun: () => void; onSend: () => void;
}) {
  return (
    <div className="step-layout">
      <div className="step-form">
        <StepIntro number="04" title="제출 현황을 확인하세요" description="제출자와 마감일을 비교해 미제출·지각 대상을 찾고 리마인드를 작성합니다." />
        <Field label="제출 식별자" hint="팀명 또는 제출자명을 쉼표로 구분하세요."><input name="submitted-identifiers" autoComplete="off" value={props.submitted} onChange={(e) => props.setSubmitted(e.target.value)} /></Field>
        <Field label="마감일"><input name="deadline" autoComplete="off" value={props.deadline} onChange={(e) => props.setDeadline(e.target.value)} /></Field>
        <button className="button primary-button full" onClick={props.onRun} disabled={props.loading}>{props.loading && !props.result ? <><Spinner /> 현황 확인 중…</> : "제출 현황 확인"}</button>
      </div>
      <div className="step-result">
        <ResultHeader title="리마인드" meta={props.result ? `제출률 ${Math.round(props.result.submission_rate * 100)}%` : "실행 전"} />
        {!props.result ? <EmptyState title="미제출자와 메일 초안이 나타납니다" description="사람은 대상과 문장만 확인하면 됩니다." /> : (
          <>
            <div className="result-metrics compact-metrics">
              <Metric label="제출" value={props.result.submitted_list.length} detail="완료" />
              <Metric label="미제출" value={props.result.missing_list.length} detail="리마인드 대상" accent={props.result.missing_list.length > 0} />
              <Metric label="지각" value={props.result.late_list.length} detail="마감 후 제출" />
            </div>
            <Field label="제목"><input name="reminder-subject" autoComplete="off" value={props.reminderSubject} onChange={(e) => props.setReminderSubject(e.target.value)} /></Field>
            <Field label="본문"><textarea name="reminder-body" autoComplete="off" rows={8} value={props.reminderBody} onChange={(e) => props.setReminderBody(e.target.value)} /></Field>
            <Field label="수신자"><input name="reminder-recipients" inputMode="email" autoComplete="off" spellCheck={false} value={props.reminderRecipients} onChange={(e) => props.setReminderRecipients(e.target.value)} /></Field>
            <button className="button primary-button full" onClick={props.onSend} disabled={props.loading || !props.result.missing_list.length}>리마인드 보내기</button>
            {props.sent && <SentCard result={props.sent} />}
          </>
        )}
      </div>
    </div>
  );
}

function SyncStep({ referenceFile, setReferenceFile, targetFiles, setTargetFiles, result, loading, hint, onMakeSamples, onRun }: {
  referenceFile: File | null; setReferenceFile: (file: File | null) => void; targetFiles: File[]; setTargetFiles: (files: File[]) => void;
  result: SyncCommonFieldsResponse | null; loading: boolean; hint: string | null; onMakeSamples: () => void; onRun: () => void;
}) {
  return (
    <div className="step-layout">
      <div className="step-form">
        <StepIntro number="05" title="기준 엑셀로 여러 파일을 일괄 업데이트하세요" description="기준 파일과 같은 컬럼을 찾고, 프로젝트번호가 같으면 해당 행의 값을 여러 엑셀에 동시에 반영합니다." />
        <button className="text-button sample-button" onClick={onMakeSamples}>일괄 수정 샘플 생성</button>
        {hint && <p className="inline-note">{hint}</p>}
        <Field label="기준 파일"><input name="reference-file" type="file" accept=".xlsx,.xls" onChange={(e) => setReferenceFile(e.target.files?.[0] ?? null)} /></Field>
        <Field label="수정 대상 파일"><input name="target-files" type="file" accept=".xlsx,.xls" multiple onChange={(e) => setTargetFiles(Array.from(e.target.files ?? []))} /></Field>
        <FileSummary files={[...(referenceFile ? [referenceFile] : []), ...targetFiles]} />
        <button className="button primary-button full" onClick={onRun} disabled={loading || !referenceFile || !targetFiles.length}>{loading ? "동기화 중…" : "공통 항목 동기화"}</button>
      </div>
      <div className="step-result">
        <ResultHeader title="수정 결과" meta={result ? `${result.downloads.length}개 파일 완료` : "실행 전"} />
        {!result ? <EmptyState title="변경 요약이 여기에 나타납니다" description="원본은 보존되고 수정본을 별도로 다운로드합니다." /> : (
          <>
            <div className="result-metrics compact-metrics">
              <Metric label="수정 파일" value={result.downloads.length} detail="원본 보존" />
              <Metric label="변경 셀" value={result.update_count} detail="자동 반영" />
              <Metric label="공통 컬럼" value={result.common_columns.length} detail={result.key_column || "행 기준"} />
            </div>
            <div className="download-row">{result.downloads.map((url, index) => <a className="button secondary-button" href={url} key={url}>수정본 {index + 1}</a>)}</div>
          </>
        )}
      </div>
    </div>
  );
}

function StepIntro({ number, title, description }: { number: string; title: string; description: string }) {
  return <div className="step-intro"><span>{number}</span><div><h2>{title}</h2><p>{description}</p></div></div>;
}

function ResultHeader({ title, meta }: { title: string; meta: string }) {
  return <div className="result-header"><h2>{title}</h2><span>{meta}</span></div>;
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

function FileSummary({ files }: { files: File[] }) {
  if (!files.length) return null;
  return <ul className="file-summary">{files.map((file) => <li key={`${file.name}-${file.size}`}><span>XL</span>{file.name}<small>{Math.ceil(file.size / 1024)}KB</small></li>)}</ul>;
}

function Metric({ label, value, detail, accent, danger }: { label: string; value: number | string; detail: string; accent?: boolean; danger?: boolean }) {
  return <div className={`metric ${accent ? "accent" : ""} ${danger ? "danger" : ""}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge badge-${status}`}><i />{STATUS_LABEL[status] ?? status}</span>;
}

function SentCard({ result }: { result: SendRequestMailResponse }) {
  return <div className="success-card"><span>{result.mode === "mock" ? "Mock 발송 완료" : "발송 완료"}</span><strong>{result.recipients.length}명 · 첨부 {result.attachments.length}개</strong><small>{result.message_id}</small></div>;
}

function EmptyState({ title, description, compact }: { title: string; description: string; compact?: boolean }) {
  return <div className={`empty-state ${compact ? "compact" : ""}`}><span className="empty-mark">·</span><strong>{title}</strong><p>{description}</p></div>;
}

function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

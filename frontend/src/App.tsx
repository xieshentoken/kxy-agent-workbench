import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { create } from 'zustand'
import {
  addEdge,
  Background,
  Connection,
  Controls,
  Edge,
  EdgeChange,
  Handle,
  MiniMap,
  Node,
  NodeChange,
  NodeProps,
  Panel,
  Position,
  ReactFlow,
  ReactFlowInstance,
  SelectionMode,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import {
  ArrowLeft,
  Archive,
  ArrowDownToLine,
  ArrowUpFromLine,
  BookOpen,
  Boxes,
  Check,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleX,
  CircleHelp,
  ClipboardCheck,
  Code2,
  CornerDownLeft,
  Download,
  FileImage,
  FileText,
  Filter,
  FolderOpen,
  GitBranch,
  Hand,
  KeyRound,
  HardDrive,
  LayoutTemplate,
  LoaderCircle,
  MousePointer2,
  PackageOpen,
  MoreHorizontal,
  Palette,
  PanelLeft,
  PanelRight,
  PenLine,
  Play,
  Plus,
  RefreshCw,
  Save,
  Server,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Upload,
  Undo2,
  Workflow,
  X,
} from 'lucide-react'
import {
  AgentModel,
  AgentModelInput,
  AgentProfile,
  Appearance,
  Credential,
  CredentialStoreInput,
  CredentialUpdateInput,
  CredentialTestInput,
  CredentialTestResult,
  DEFAULT_APPEARANCE,
  DEFAULT_ANALYZER_PROMPT,
  DEFAULT_ANALYZER_SETTING,
  DEFAULT_OUTPUT_DEFAULTS,
  DefaultAnalyzerSetting,
  DefaultAnalyzerUpdate,
  DependencyCacheRecord,
  DependencyCheckResponse,
  DependencySkillResult,
  GlobalSettingsPanel,
  LocalFont,
  McpCandidate,
  McpRecord,
  OutputDefaults,
  Skill,
  mergeAgentProfiles,
} from './v2'
import { CanvasEffects } from './v3'

type NodeKind = 'file' | 'text' | 'input' | 'analyzer' | 'condition' | 'container'
  | 'filter' | 'human' | 'blackbox' | 'subflow_input' | 'subflow_output'
type OutputFormat = 'auto' | 'markdown' | 'text' | 'json'
type ReplyExportFormat = Exclude<OutputFormat, 'auto'>
type LoopFeedback = {
  latest_result: boolean
  issues: boolean
  next_action: boolean
  history_summary: boolean
}
type LoopReviewFields = {
  passed: string
  issues: string
  next_action: string
}
type LoopConfig = {
  enabled: boolean
  executor_id: string
  reviewer_id: string
  goal: string
  input_field: string
  review_fields: LoopReviewFields
  feedback: LoopFeedback
  max_rounds: number
  active_budget_seconds: number
  previous_summary_chars: number
}
type KxyNodeData = {
  label: string
  kind?: NodeKind
  text?: string
  file_id?: string
  fileStatus?: string
  fileName?: string
  file_ids?: string[]
  attachments?: Array<{ file_id: string; name?: string; relative_path: string; display_name: string }>
  prompt?: string
  cli?: string
  agent_id?: string
  model?: string
  model_ref?: string
  variant?: string
  effort?: string
  timeout?: number
  network?: boolean
  expect_json?: boolean
  output_format?: OutputFormat
  output_schema?: Record<string, unknown>
  export_formats?: ReplyExportFormat[]
  allowed_file_extensions?: string[]
  json_mode?: 'content' | 'full'
  mcp_ids?: string[]
  field?: string
  operator?: string
  expected?: string
  missing_strategy?: 'error' | 'false' | 'true'
  name_pattern?: string
  pattern_mode?: 'glob' | 'regex'
  name_scope?: 'basename' | 'relative_path'
  extensions?: string[]
  custom_extensions?: string
  timeout_ms?: number
  grant_id?: string
  credential_id?: string
  skill_ids?: string[]
  confirm_label?: string
  workflow?: Workflow
  loop?: LoopConfig
  loop_status?: string
  loop_round?: number
  inner_status?: string
  [key: string]: unknown
}
type KxyNode = Node<KxyNodeData>
type Workflow = {
  id?: string
  name: string
  version: string
  nodes: KxyNode[]
  edges: Edge[]
  settings?: Record<string, unknown>
}
type FileAsset = {
  id: string
  display_name: string
  sha256: string
  mime: string
  size: number
  status: string
  preview?: string
  metadata?: Record<string, unknown>
}
type Run = {
  id: string
  status: string
  error?: string | null
  attempts?: Array<{ attempt_no: number; status: string; reason?: string | null; reused_nodes?: string[]; rerun_nodes?: string[]; error?: string | null; created_at?: string; started_at?: string | null; finished_at?: string | null }>
  output_manifest?: { outputs?: Record<string, unknown>; artifacts?: Array<{ name: string; path: string; size: number; sha256: string; url: string }>; granted_outputs?: Array<{ node_id: string; path: string; granted?: boolean }> } | null
  nodes?: Array<{ node_id: string; node_path?: string; status: string; message?: string | null; output?: Record<string, unknown> | null }>
  loop_rounds?: Array<{
    run_id: string
    attempt_no: number
    loop_path: string
    round_no: number
    status: string
    original_goal?: string
    original_input?: unknown
    previous_summary?: string
    executor_node_id?: string
    executor_input?: unknown
    executor_output?: unknown
    reviewer_node_id?: string
    reviewer_input?: unknown
    reviewer_output?: unknown
    review_passed?: boolean | null
    review_issues?: string[]
    next_action?: string | null
    active_seconds?: number
    effective_max_rounds?: number
    budget_seconds?: number
    node_outputs?: Record<string, unknown>
    node_statuses?: Record<string, string>
    control?: string | null
    control_payload?: Record<string, unknown>
    error?: string | null
  }>
  events?: Array<{ id: number; type?: string; event_type?: string; payload: Record<string, unknown>; created_at: string }>
  approvals?: Array<{
    node_id: string
    status: string
    content?: string
    confirm_label?: string
    inputs?: unknown
    decision?: string | null
    note?: string | null
    original_inputs?: unknown
    allow_return?: boolean
    revision_text?: string | null
    revision_note?: string | null
    revision_at?: string | null
    created_at?: string
    decided_at?: string | null
  }>
}
type WorkflowRecord = { id: string; name: string; workflow: Workflow; updated_at?: string }
type RunSummary = { id: string; workflow_id?: string | null; status: string; error?: string | null; created_at: string; finished_at?: string | null }
type PresetKind = Exclude<NodeKind, 'subflow_input' | 'subflow_output'>
type ComponentPreset = { id: string; name: string; kind: PresetKind; source?: string; config: Record<string, unknown>; created_at?: string; updated_at?: string }
type CliStatus = { name: string; available: boolean; status: string; version?: string | null }
type SettingsResponse = Appearance & {
  agent_check_on_settings_open?: boolean
  auto_check_mounts?: boolean
  default_analyzer?: DefaultAnalyzerSetting
  output_defaults?: OutputDefaults
}
type EditorSnapshot = {
  workflowName: string
  workflowId?: string
  nodes: KxyNode[]
  edges: Edge[]
  canvasStack: Array<{ nodeId: string; name: string; workflowId?: string; nodes: KxyNode[]; edges: Edge[] }>
}

type PortableAttachmentPreview = {
  source_id: string
  sha256: string
  size: number
  display_name: string
  mime?: string
  included?: boolean
  status: 'matched' | 'carried' | 'missing' | string
  candidates: Array<{ id: string; display_name: string; size: number; sha256: string }>
}
type PortableSkillPreview = {
  source_id: string
  name: string
  description?: string
  snapshot_hash: string
  file_count?: number
  byte_count?: number
  declarations?: Record<string, unknown>
  included?: boolean
  status: 'matched' | 'carried' | 'missing' | string
  candidates: Array<{ id: string; name: string; snapshot_hash: string }>
}
type PortableModelCandidate = {
  id: string
  agent_id?: string
  cli_id?: string
  model?: string
  alias?: string
  source?: string
  efforts?: string[]
  default_effort?: string
}
type PortableModelPreview = {
  key: string
  node_path?: string
  node_name?: string
  agent_id?: string
  model_ref?: string
  model?: string
  alias?: string
  effort?: string
  default_effort?: string
  status: string
  candidates: PortableModelCandidate[]
}
type PortableMcpPreview = {
  source_id: string
  name?: string
  transport?: string
  status: string
  candidates: McpRecord[]
}
type PortableOutputPreview = {
  key: string
  node_path?: string
  node_name?: string
  status: string
  candidates: Array<{ mode: 'default' | 'grant'; id: string; name: string; path?: string; active?: boolean }>
}
type PortablePreview = {
  preview_id: string
  expires_at: string
  workflow: { name: string; version: string; nodes: number; edges: number }
  manifest: Record<string, unknown>
  resources: { attachments: PortableAttachmentPreview[]; skills: PortableSkillPreview[] }
  dependencies: { models: PortableModelPreview[]; mcps: PortableMcpPreview[]; outputs: PortableOutputPreview[] }
}
type PortableBindings = {
  files: Record<string, string>
  skills: Record<string, string>
  models: Record<string, { model_ref: string; effort?: string }>
  mcps: Record<string, string>
  outputs: Record<string, { mode: '' | 'default' | 'grant'; grant_id?: string }>
}

function emptyPortableBindings(): PortableBindings {
  return { files: {}, skills: {}, models: {}, mcps: {}, outputs: {} }
}

type SkillHubSyncAction = 'repair' | 'add' | 'restore'
type SkillHubScanItem = {
  key: string
  status: string
  name: string
  skill_id?: string | null
  upstream_skill_id?: string | null
  snapshot_hash?: string | null
  manifest_fingerprint?: string | null
  fingerprint: string
  reason?: string | null
  actions: SkillHubSyncAction[]
}
type SkillHubScan = {
  scan_fingerprint: string
  counts: Record<string, number>
  items: SkillHubScanItem[]
}
type SkillHubSyncResult = {
  status: string
  scan_fingerprint?: string
  results: Array<{ key?: string; action?: SkillHubSyncAction; status: string; skill_id?: string; upstream_skill_id?: string; reason?: string }>
}
type BulkDeleteResult = {
  status: string
  deleted: string[]
  failed: Array<{ id: string; reason?: string; deleted?: boolean }>
  results?: Array<{ id: string; ok: boolean; deleted?: boolean; reason?: string }>
}

const skillHubStatusLabels: Record<string, string> = {
  unchanged: '一致',
  repairable: '可修复',
  new: '待纳入',
  deleted: '已删除 · 可恢复',
  missing: '缺失',
  stale: '过期',
  conflict: '冲突',
}
const skillHubActionLabels: Record<SkillHubSyncAction, string> = {
  repair: '修复映射',
  add: '纳入本机',
  restore: '明确恢复',
}

const API = import.meta.env.VITE_API_URL || ''

const iconForKind: Record<NodeKind, typeof FileText> = {
  file: FileText,
  text: FileText,
  input: ArrowUpFromLine,
  filter: Filter,
  analyzer: Sparkles,
  condition: GitBranch,
  container: Archive,
  human: ClipboardCheck,
  blackbox: Boxes,
  subflow_input: ArrowUpFromLine,
  subflow_output: ArrowDownToLine,
}

const toneForKind: Record<NodeKind, string> = {
  file: 'tone-sage',
  text: 'tone-sage',
  input: 'tone-sage',
  filter: 'tone-lilac',
  analyzer: 'tone-apricot',
  condition: 'tone-lilac',
  container: 'tone-blue',
  human: 'tone-lilac',
  blackbox: 'tone-blue',
  subflow_input: 'tone-sage',
  subflow_output: 'tone-blue',
}

const WORKSPACE_PROMPT_HINT = '如需读取本次运行资料，请打开 input-context.json；输入文件副本位于 inputs/。若已选择 Skill，请读取 skill-manifest.json 中列出的快照；生成文件请写入 outputs/。'
const LOOP_REVIEWER_PROMPT = `请根据可见的原始目标、最新执行器结果和上一轮反馈审阅本轮结果。只返回一个 JSON 对象，格式必须是：{"passed":true或false,"issues":["问题"],"next_action":"下一步"}。passed 必须是布尔值，issues 必须是字符串数组，next_action 必须是字符串。不要输出 Markdown，不要增加其他字段。\n\n${WORKSPACE_PROMPT_HINT}`

const defaultLoopConfig = (executorId = 'executor', reviewerId = 'reviewer'): LoopConfig => ({
  enabled: true,
  executor_id: executorId,
  reviewer_id: reviewerId,
  goal: '',
  input_field: 'text',
  review_fields: { passed: 'passed', issues: 'issues', next_action: 'next_action' },
  feedback: { latest_result: true, issues: true, next_action: true, history_summary: true },
  max_rounds: 3,
  active_budget_seconds: 1800,
  previous_summary_chars: 4000,
})

const defaultNodeData = (kind: NodeKind): KxyNodeData => {
  const common = { label: kind === 'file' ? '资料节点' : kind === 'analyzer' ? '分析器' : kind === 'condition' ? '条件分支' : kind === 'filter' ? '文件过滤' : kind === 'container' ? '授权输出' : kind === 'human' ? '人工确认' : kind === 'blackbox' ? '黑盒子' : kind === 'subflow_input' ? '子流程输入' : kind === 'subflow_output' ? '子流程输出' : '输入', kind }
  if (kind === 'analyzer') return { ...common, prompt: DEFAULT_ANALYZER_PROMPT, cli: 'codex', model: '', model_ref: '', variant: '', effort: '', timeout: 600, network: true, expect_json: false, output_format: 'auto', skill_ids: [], mcp_ids: [] }
  if (kind === 'condition') return { ...common, field: 'status', operator: 'equals', expected: 'succeeded', missing_strategy: 'error' }
  if (kind === 'filter') return { ...common, name_pattern: '*', pattern_mode: 'glob', name_scope: 'basename', extensions: ['*'], custom_extensions: '', timeout_ms: 100 }
  if (kind === 'container') return { ...common, grant_id: '', export_formats: [], allowed_file_extensions: [], json_mode: 'full' }
  if (kind === 'human') return { ...common, content: '请检查上游研究结果，确认后继续。', confirm_label: '确认继续', review_gate: false }
  if (kind === 'blackbox') return { ...common, workflow: defaultBlackboxWorkflow(), text: '' }
  return { ...common, text: '', ...(kind === 'input' ? { file_ids: [], attachments: [] } : {}) }
}

function applyAnalyzerDefault(data: KxyNodeData, setting: DefaultAnalyzerSetting, applyPrompt = true): KxyNodeData {
  const agentId = setting.agent_id || 'codex'
  const nextData = applyPrompt ? { ...data, prompt: setting.prompt ?? DEFAULT_ANALYZER_PROMPT } : data
  if (setting.mode === 'model' && setting.model_ref) {
    return {
      ...nextData,
      cli: agentId,
      agent_id: agentId,
      model_ref: setting.model_ref,
      model: '',
      variant: '',
      effort: setting.effort || '',
    }
  }
  return {
    ...nextData,
    cli: agentId,
    agent_id: agentId,
    model: '',
    model_ref: '',
    variant: '',
    effort: '',
  }
}

function newNodeData(kind: NodeKind, defaultAnalyzer: DefaultAnalyzerSetting, outputDefaults: OutputDefaults): KxyNodeData {
  const data = defaultNodeData(kind)
  if (kind === 'analyzer') return applyAnalyzerDefault(data, defaultAnalyzer)
  if (kind === 'container') {
    return {
      ...data,
      export_formats: [...outputDefaults.export_formats],
      allowed_file_extensions: [...outputDefaults.allowed_file_extensions],
      json_mode: outputDefaults.json_mode,
    }
  }
  return data
}

const BLACKBOX_PAD_X = 220
const BLACKBOX_PAD_Y = 40

function defaultBlackboxWorkflow(label = '黑盒子'): Workflow {
  const inputId = 'subflow-input'
  const outputId = 'subflow-output'
  return {
    name: `${label} 内部`,
    version: 'kxy.workflow.v1',
    nodes: [
      { id: inputId, type: 'subflow_input', position: { x: 50, y: 120 }, data: defaultNodeData('subflow_input') },
      { id: outputId, type: 'subflow_output', position: { x: 390, y: 120 }, data: defaultNodeData('subflow_output') },
    ],
    edges: [{ id: 'subflow-pass-through', source: inputId, target: outputId, sourceHandle: 'result', targetHandle: 'items' }],
  }
}

function defaultLoopBlackboxWorkflow(label = '有界循环', defaultAnalyzer = DEFAULT_ANALYZER_SETTING, withHumanGate = false): Workflow {
  const inputId = 'subflow-input'
  const executorId = 'executor'
  const reviewerId = 'reviewer'
  const gateId = 'review-gate'
  const outputId = 'subflow-output'
  const executor = applyAnalyzerDefault({
    ...defaultNodeData('analyzer'),
    label: '执行器',
    prompt: `基于可见的循环上下文执行原始目标。明确保留输入、当前结果和可验证边界。\n\n${WORKSPACE_PROMPT_HINT}`,
  }, defaultAnalyzer, false)
  const reviewer = applyAnalyzerDefault({
    ...defaultNodeData('analyzer'),
    label: '审阅器',
    prompt: LOOP_REVIEWER_PROMPT,
    expect_json: true,
    output_format: 'json' as OutputFormat,
  }, defaultAnalyzer, false)
  const gate = { id: gateId, type: 'human' as const, position: { x: 900, y: 120 }, data: { ...defaultNodeData('human'), label: '审阅闸门', content: '请阅读审阅器结果；可直接编辑修订副本。通过后进入循环输出，退回会把反馈带入下一轮。', confirm_label: '通过并继续', review_gate: true } }
  return {
    name: `${label} 内部`,
    version: 'kxy.workflow.v1',
    nodes: [
      { id: inputId, type: 'subflow_input', position: { x: 40, y: 120 }, data: defaultNodeData('subflow_input') },
      { id: executorId, type: 'analyzer', position: { x: 300, y: 120 }, data: executor },
      { id: reviewerId, type: 'analyzer', position: { x: 600, y: 120 }, data: reviewer },
      ...(withHumanGate ? [gate] : []),
      { id: outputId, type: 'subflow_output', position: { x: withHumanGate ? 1180 : 900, y: 120 }, data: defaultNodeData('subflow_output') },
    ],
    edges: [
      { id: 'loop-input-executor', source: inputId, target: executorId, sourceHandle: 'result', targetHandle: 'items' },
      { id: 'loop-executor-reviewer', source: executorId, target: reviewerId, sourceHandle: 'result', targetHandle: 'items' },
      ...(withHumanGate ? [
        { id: 'loop-reviewer-gate', source: reviewerId, target: gateId, sourceHandle: 'result', targetHandle: 'items' },
        { id: 'loop-gate-output', source: gateId, target: outputId, sourceHandle: 'result', targetHandle: 'items' },
      ] : [{ id: 'loop-reviewer-output', source: reviewerId, target: outputId, sourceHandle: 'result', targetHandle: 'items' }]),
    ],
  }
}

function defaultLoopNodeData(defaultAnalyzer = DEFAULT_ANALYZER_SETTING, withHumanGate = false): KxyNodeData {
  return {
    ...defaultNodeData('blackbox'),
    label: '有界循环',
    workflow: defaultLoopBlackboxWorkflow(withHumanGate ? '有界循环（人工审阅）' : '有界循环', defaultAnalyzer, withHumanGate),
    loop: defaultLoopConfig(),
  }
}

const defaultWorkflow: Workflow = {
  id: 'local-draft',
  name: '未命名研究流程',
  version: 'kxy.workflow.v1',
  nodes: [
    { id: 'source', type: 'input', position: { x: 40, y: 260 }, data: { ...defaultNodeData('input'), label: '研究问题与资料', text: '从这里开始：写下研究问题，或追加一份/一组资料。' } },
    { id: 'analyzer', type: 'analyzer', position: { x: 310, y: 260 }, data: { ...defaultNodeData('analyzer'), label: '事实提取', prompt: `从输入中提取可核查事实，并保留页码、段落或表格行号。\n\n${WORKSPACE_PROMPT_HINT}` } },
    { id: 'output', type: 'container', position: { x: 580, y: 260 }, data: { ...defaultNodeData('container'), label: '研究输出' } },
  ],
  edges: [
    { id: 'e-source-analyzer', source: 'source', target: 'analyzer', sourceHandle: 'result', targetHandle: 'items' },
    { id: 'e-analyzer-output', source: 'analyzer', target: 'output', sourceHandle: 'result', targetHandle: 'items' },
  ],
}

const useUiStore = create<{
  appearance: Appearance
  setAppearance: (patch: Partial<Appearance>) => void
}>((set) => ({
  appearance: DEFAULT_APPEARANCE,
  setAppearance: (patch) => set((state) => ({ appearance: { ...state.appearance, ...patch } })),
}))

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json() as { detail?: unknown }
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      // Preserve the HTTP status when the server did not return JSON.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

async function apiOr<T>(path: string, fallback: T, init?: RequestInit): Promise<T> {
  try {
    return await api<T>(path, init)
  } catch {
    return fallback
  }
}

const supportedNodeKinds: NodeKind[] = ['file', 'text', 'input', 'filter', 'analyzer', 'condition', 'container', 'human', 'blackbox', 'subflow_input', 'subflow_output']

function normalizeNodeKind(value: unknown): NodeKind {
  return typeof value === 'string' && supportedNodeKinds.includes(value as NodeKind) ? value as NodeKind : 'text'
}

function flowFromWorkflow(input: Workflow): Workflow {
  return {
    ...input,
    nodes: (input.nodes || []).map((node) => {
      const nodeData = (node.data || {}) as KxyNodeData
      const kind = normalizeNodeKind(node.type || nodeData.kind)
      const nested = kind === 'blackbox' && nodeData.workflow && typeof nodeData.workflow === 'object' ? flowFromWorkflow(nodeData.workflow) : undefined
      const mergedData = { ...defaultNodeData(kind), ...nodeData, ...(nested ? { workflow: nested } : {}), kind } as KxyNodeData
      if (kind === 'analyzer' && !nodeData.output_format) mergedData.output_format = nodeData.expect_json ? 'json' : 'auto'
      return { ...node, type: kind, data: mergedData }
    }),
    edges: input.edges || [],
  }
}

function stripExportValue(value: unknown, schemaContext = false): unknown {
  if (Array.isArray(value)) return value.map((item) => stripExportValue(item, schemaContext))
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).filter(([key]) => schemaContext || (!/key|token|secret|password/i.test(key) && !['credential_id', 'credentialId', 'grant_id', 'grantId'].includes(key))).map(([key, item]) => [key, stripExportValue(item, schemaContext || key === 'output_schema')]))
}

function stripExportSecrets(workflow: Workflow): Workflow {
  return stripExportValue(workflow) as Workflow
}

function composeRootWorkflow(
  workflowName: string,
  workflowId: string | undefined,
  nodes: KxyNode[],
  edges: Edge[],
  canvasStack: EditorSnapshot['canvasStack'],
): Workflow {
  let child: Workflow = {
    name: workflowName,
    version: 'kxy.workflow.v1',
    nodes: cloneNodesForHistory(nodes),
    edges: JSON.parse(JSON.stringify(edges)) as Edge[],
    settings: {},
  }
  for (let index = canvasStack.length - 1; index >= 0; index -= 1) {
    const frame = canvasStack[index]
    const parentNodes = cloneNodesForHistory(frame.nodes)
    const target = parentNodes.find((node) => node.id === frame.nodeId)
    if (target) target.data = { ...target.data, workflow: child }
    child = {
      name: frame.name,
      version: 'kxy.workflow.v1',
      nodes: parentNodes,
      edges: JSON.parse(JSON.stringify(frame.edges)) as Edge[],
      settings: {},
    }
  }
  return { ...child, id: canvasStack[0]?.workflowId || workflowId }
}

function portableWorkflowReferences(workflow: Workflow): { fileIds: string[]; skillIds: string[] } {
  const fileIds = new Set<string>()
  const skillIds = new Set<string>()
  const visit = (current: Workflow) => {
    current.nodes.forEach((node) => {
      const data = node.data || {}
      if (typeof data.file_id === 'string' && data.file_id) fileIds.add(data.file_id)
      data.file_ids?.forEach((id) => { if (id) fileIds.add(id) })
      data.attachments?.forEach((item) => { if (item.file_id) fileIds.add(item.file_id) })
      data.skill_ids?.forEach((id) => { if (id) skillIds.add(id) })
      if (data.workflow && typeof data.workflow === 'object') visit(data.workflow)
    })
  }
  visit(workflow)
  return { fileIds: [...fileIds], skillIds: [...skillIds] }
}

function formatPortableBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

const presetKindLabels: Record<PresetKind, string> = {
  file: '资料节点',
  text: '文字输入',
  input: '输入节点',
  filter: '文件过滤',
  analyzer: '分析器',
  container: '授权输出',
  condition: '条件分支',
  human: '人工确认',
  blackbox: '黑盒子',
}

function stripPresetValue(value: unknown, key = ''): unknown {
  if (Array.isArray(value)) return value.map((item) => stripPresetValue(item, key)).filter((item) => item !== undefined)
  if (!value || typeof value !== 'object') return value
  const lower = key.toLowerCase()
  if (lower === 'output_schema') return value
  const result: Record<string, unknown> = {}
  for (const [childKey, childValue] of Object.entries(value)) {
    const childLower = childKey.toLowerCase()
    if (['runtime_status', 'skill_names', 'inner_status', 'selected', 'measured', 'width', 'height', 'initialwidth', 'initialheight', 'resizing', 'dragging'].includes(childLower)) continue
    if (/^(api[_-]?key|token|access[_-]?token|refresh[_-]?token|secret|password|authorization)$/i.test(childKey) || /(?:api[_-]?key|password|secret)$/i.test(childKey)) continue
    const next = stripPresetValue(childValue, childKey)
    if (next !== undefined) result[childKey] = next
  }
  return result
}

function presetConfigFromData(data: KxyNodeData): Record<string, unknown> {
  const config = stripPresetValue(data) as Record<string, unknown>
  delete config.id
  return config
}

function presetMissingReferences(
  preset: ComponentPreset,
  files: FileAsset[],
  skills: Skill[],
  models: AgentModel[],
  grants: Array<{ id: string; revoked_at?: string | null }>,
  credentials: Credential[],
  mcps: McpRecord[],
): string[] {
  const missing = new Set<string>()
  const fileIds = new Set(files.map((item) => item.id))
  const skillIds = new Set(skills.map((item) => item.id))
  const modelIds = new Set(models.map((item) => item.id))
  const grantIds = new Set(grants.filter((item) => !item.revoked_at).map((item) => item.id))
  const credentialIds = new Set(credentials.map((item) => item.id))
  const mcpIds = new Set(mcps.filter((item) => item.supported !== false).map((item) => item.id))
  const visit = (value: unknown, path: string) => {
    if (!value || typeof value !== 'object') return
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${path}[${index}]`))
      return
    }
    const data = value as Record<string, unknown>
    const fileId = typeof data.file_id === 'string' ? data.file_id : ''
    if (fileId && !fileIds.has(fileId)) missing.add(`资料 ${fileId}`)
    if (Array.isArray(data.file_ids)) data.file_ids.forEach((id) => { if (typeof id === 'string' && !fileIds.has(id)) missing.add(`资料 ${id}`) })
    if (Array.isArray(data.attachments)) data.attachments.forEach((attachment) => {
      if (attachment && typeof attachment === 'object' && typeof (attachment as Record<string, unknown>).file_id === 'string' && !fileIds.has((attachment as Record<string, unknown>).file_id as string)) missing.add(`资料 ${(attachment as Record<string, unknown>).file_id as string}`)
    })
    const modelRef = typeof data.model_ref === 'string' ? data.model_ref : ''
    if (modelRef && !modelIds.has(modelRef)) missing.add(`模型 ${modelRef}`)
    const credentialId = typeof data.credential_id === 'string' ? data.credential_id : ''
    if (credentialId && !credentialIds.has(credentialId)) missing.add(`凭据引用 ${credentialId}`)
    const grantId = typeof data.grant_id === 'string' ? data.grant_id : ''
    if (grantId && !grantIds.has(grantId)) missing.add(`输出授权 ${grantId}`)
    const skillList = data.skill_ids
    if (Array.isArray(skillList)) skillList.forEach((id) => { if (typeof id === 'string' && !skillIds.has(id)) missing.add(`Skill ${id}`) })
    const mcpList = data.mcp_ids
    if (Array.isArray(mcpList)) mcpList.forEach((id) => { if (typeof id === 'string' && !mcpIds.has(id)) missing.add(`MCP ${id}`) })
    if (data.workflow && typeof data.workflow === 'object') visit(data.workflow, `${path}.workflow`)
    if (Array.isArray(data.nodes)) data.nodes.forEach((node, index) => {
      if (node && typeof node === 'object' && !Array.isArray(node)) {
        const nodeRecord = node as Record<string, unknown>
        visit(nodeRecord.data || nodeRecord, `${path}.nodes[${index}]`)
      }
    })
  }
  visit(preset.config, preset.kind)
  return [...missing]
}

function remapLoopReferences(loop: LoopConfig, sourceNodes: KxyNode[], targetNodes: KxyNode[]): LoopConfig {
  const idMap = new Map(sourceNodes.map((node, index) => [node.id, targetNodes[index]?.id || node.id]))
  const next = { ...loop }
  for (const role of ['executor_id', 'reviewer_id'] as const) {
    const oldId = next[role]
    if (typeof oldId === 'string' && idMap.has(oldId)) next[role] = idMap.get(oldId) || oldId
  }
  return next
}

function remapPresetWorkflow(input: Workflow, prefix: string): Workflow {
  const source = flowFromWorkflow(input)
  const base = (prefix.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 72) || 'preset')
  const idMap = new Map(source.nodes.map((node, index) => [node.id, `${base}__n${index + 1}`]))
  const nodes = source.nodes.map((node, index) => {
    const nestedSource = node.data.kind === 'blackbox' && node.data.workflow ? flowFromWorkflow(node.data.workflow) : undefined
    const nested = nestedSource ? remapPresetWorkflow(nestedSource, `${base}b${index + 1}`) : undefined
    let data: KxyNodeData = { ...node.data }
    if (nested && nestedSource) {
      data = { ...data, workflow: nested }
      if (data.loop && typeof data.loop === 'object') {
        data.loop = remapLoopReferences(data.loop, nestedSource.nodes, nested.nodes)
      }
    }
    return cloneNode(node, {
      id: idMap.get(node.id) || `${base}__n${index + 1}`,
      data,
    })
  })
  const edges = source.edges.map((edge, index) => ({
    ...edge,
    id: `${prefix}__e${index + 1}`,
    source: idMap.get(edge.source) || edge.source,
    target: idMap.get(edge.target) || edge.target,
  }))
  return { ...source, nodes, edges }
}

function NodeCard({ data, selected }: NodeProps<KxyNode>) {
  const kind = data.kind || 'text'
  const Icon = iconForKind[kind]
  const tone = toneForKind[kind]
  const skillNames = Array.isArray(data.skill_names) ? data.skill_names.filter((name): name is string => typeof name === 'string') : []
  const runtimeStatus = typeof data.runtime_status === 'string' ? data.runtime_status : ''
  const statusLabel = runtimeStatus === 'succeeded' ? '完成' : runtimeStatus === 'failed' ? '失败' : runtimeStatus === 'running' ? '运行' : runtimeStatus === 'skipped' ? '跳过' : runtimeStatus === 'waiting' ? '待确认' : runtimeStatus === 'rejected' ? '已拒绝' : runtimeStatus === 'interrupted' ? '已中断' : runtimeStatus === 'pending' ? '等待' : ''
  const kindLabel = kind === 'file' ? '资料' : kind === 'analyzer' ? '分析器' : kind === 'condition' ? '条件' : kind === 'filter' ? '过滤' : kind === 'container' ? '输出' : kind === 'human' ? '人工' : kind === 'blackbox' ? (data.loop?.enabled ? '有界循环' : '黑盒子') : kind === 'subflow_input' ? '入口' : kind === 'subflow_output' ? '出口' : '输入'
  const loopStatus = typeof data.loop_status === 'string' ? data.loop_status : ''
  const loopRound = typeof data.loop_round === 'number' ? data.loop_round : 0
  const loopSummary = data.loop?.enabled ? `第 ${loopRound || '—'} 轮 · ${loopStatus === 'budget_waiting' ? '预算暂停' : loopStatus === 'round_limit_waiting' ? '轮数暂停' : loopStatus === 'reviewed' ? '等待下一轮' : '有界执行'}` : ''
  const summary = kind === 'file' ? data.fileName || '等待资料' : kind === 'analyzer' ? `${data.cli || '选择 Agent'} · ${data.output_format || (data.expect_json ? 'json' : 'auto')}` : kind === 'condition' ? `${data.field || '字段'} ${data.operator || 'equals'} · 缺失${data.missing_strategy || 'error'}` : kind === 'filter' ? `${data.pattern_mode || 'glob'} ${data.name_pattern || '*'} · ${(data.extensions || ['*']).join(',')}` : kind === 'container' ? `回复 ${(data.export_formats || []).join(' · ') || '仅界面'} · 文件 ${(data.allowed_file_extensions || []).join(' · ') || '不接收'}` : kind === 'human' ? data.confirm_label || '等待人工确认' : kind === 'blackbox' ? data.loop?.enabled ? `${loopSummary} · 双击进入` : `${data.workflow?.nodes?.filter((node) => !['subflow_input', 'subflow_output'].includes(String(node.type))).length || 0} 个内部节点 · 双击进入` : kind === 'subflow_input' || kind === 'subflow_output' ? 'items / result 边界' : data.text || ((data.attachments || []).length > 0 ? `${data.attachments?.length} 个附件` : '输入内容')
  return (
    <div className={`kxy-node ${tone} ${selected ? 'is-selected' : ''}`}>
      {kind !== 'file' && kind !== 'text' && kind !== 'input' && kind !== 'subflow_input' && <Handle type="target" position={Position.Left} id="items" className="node-handle target-handle" />}
      <div className="node-topline">
        <div className="node-icon"><Icon size={16} strokeWidth={1.8} /></div>
        <span className="node-kind">{kindLabel}</span>
        <MoreHorizontal size={16} className="node-menu" />
      </div>
      <div className="node-label" title={data.label || '未命名节点'}>{data.label || '未命名节点'}</div>
      <div className="node-summary" title={summary}>{summary}</div>
      {(skillNames.length > 0 || statusLabel) && <div className="node-badges">{skillNames.length > 0 && <span className="skill-badge node-skill-badge" title={skillNames.join('、')}><ShieldCheck size={10} />Skill {skillNames.length > 1 ? `×${skillNames.length}` : skillNames[0]}</span>}{statusLabel && <span className={`runtime-badge runtime-${runtimeStatus}`}><span className="runtime-dot" />{statusLabel}</span>}</div>}
      {kind === 'condition' ? (
        <>
          <Handle type="source" position={Position.Right} id="true" className="node-handle source-handle true-handle" />
          <Handle type="source" position={Position.Right} id="false" className="node-handle source-handle false-handle" />
          <span className="branch-label branch-true">真</span><span className="branch-label branch-false">假</span>
        </>
      ) : !['subflow_output'].includes(kind) && <Handle type="source" position={Position.Right} id="result" className="node-handle source-handle" />}
    </div>
  )
}

function SectionTitle({ icon: Icon, children, action }: { icon: typeof Boxes; children: React.ReactNode; action?: React.ReactNode }) {
  return <div className="section-title"><span><Icon size={15} />{children}</span>{action}</div>
}

function LibraryPanel({
  onAdd,
  onUpload,
  onUploadFolder,
  skills,
  onImportSkill,
  onDeleteSkill,
  onBulkDeleteSkills,
  skillHubScan,
  skillHubScanBusy,
  skillHubSyncBusy,
  onScanSkillHub,
  onSyncSkillHub,
  presets,
  onApplyPreset,
  onDeletePreset,
  files,
  models,
  grants,
  credentials,
  mcps,
  onClose,
  canAddNodes,
}: {
  onAdd: (kind: NodeKind, loop?: boolean, humanGate?: boolean) => void
  canAddNodes: boolean
  onUpload: () => void
  onUploadFolder: () => void
  skills: Skill[]
  onImportSkill: () => void
  onDeleteSkill: (id: string) => void
  onBulkDeleteSkills: (ids: string[]) => Promise<BulkDeleteResult>
  skillHubScan: SkillHubScan | null
  skillHubScanBusy: boolean
  skillHubSyncBusy: boolean
  onScanSkillHub: () => void
  onSyncSkillHub: (items: Array<{ key: string; action: SkillHubSyncAction; fingerprint: string }>) => Promise<SkillHubSyncResult>
  presets: ComponentPreset[]
  onApplyPreset: (preset: ComponentPreset) => void
  onDeletePreset: (preset: ComponentPreset) => void
  files: FileAsset[]
  models: AgentModel[]
  grants: Array<{ id: string; revoked_at?: string | null }>
  credentials: Credential[]
  mcps: McpRecord[]
  onClose: () => void
}) {
  const [expandedPresetId, setExpandedPresetId] = useState<string | null>(null)
  const [presetSort, setPresetSort] = useState<'date' | 'name'>('date')
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])
  const [selectedIndexActions, setSelectedIndexActions] = useState<Record<string, SkillHubSyncAction>>({})
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false)
  useEffect(() => {
    const available = new Set(skills.map((skill) => skill.id))
    setSelectedSkillIds((current) => current.filter((id) => available.has(id)))
  }, [skills])
  useEffect(() => {
    setSelectedIndexActions({})
  }, [skillHubScan?.scan_fingerprint])
  const normalIndexItems = (skillHubScan?.items || []).filter((item) => item.status === 'repairable' || item.status === 'new')
  const restoreIndexItems = (skillHubScan?.items || []).filter((item) => item.status === 'deleted' && item.actions.includes('restore'))
  const actionableIndexItems = [...normalIndexItems, ...restoreIndexItems]
  const selectedIndexCount = actionableIndexItems.filter((item) => selectedIndexActions[item.key]).length
  const normalSelectionComplete = normalIndexItems.length > 0 && normalIndexItems.every((item) => selectedIndexActions[item.key] === (item.status === 'repairable' ? 'repair' : 'add'))
  const skillSelectionComplete = skills.length > 0 && selectedSkillIds.length === skills.length
  const skillMutationBusy = bulkDeleteBusy || skillHubScanBusy || skillHubSyncBusy
  const toggleIndexAction = (item: SkillHubScanItem, action: SkillHubSyncAction) => {
    setSelectedIndexActions((current) => {
      const next = { ...current }
      if (next[item.key] === action) delete next[item.key]
      else next[item.key] = action
      return next
    })
  }
  const selectNormalIndexItems = () => {
    setSelectedIndexActions((current) => {
      const next = { ...current }
      normalIndexItems.forEach((item) => {
        const action: SkillHubSyncAction = item.status === 'repairable' ? 'repair' : 'add'
        if (normalSelectionComplete) delete next[item.key]
        else next[item.key] = action
      })
      return next
    })
  }
  const syncSelectedIndexItems = async () => {
    const items = actionableIndexItems.flatMap((item) => {
      const action = selectedIndexActions[item.key]
      return action ? [{ key: item.key, action, fingerprint: item.fingerprint }] : []
    })
    if (items.length === 0) return
    await onSyncSkillHub(items)
  }
  const deleteSelectedSkills = async () => {
    if (selectedSkillIds.length === 0 || bulkDeleteBusy) return
    setBulkDeleteBusy(true)
    try {
      const result = await onBulkDeleteSkills(selectedSkillIds)
      const actuallyDeleted = new Set([
        ...(result.deleted || []),
        ...(result.failed || []).filter((item) => item.deleted).map((item) => item.id),
      ])
      setSelectedSkillIds((current) => current.filter((id) => !actuallyDeleted.has(id)))
    } finally {
      setBulkDeleteBusy(false)
    }
  }
  const entries: Array<{ kind: NodeKind; label: string; detail: string; icon: typeof FileText; loop?: boolean; humanGate?: boolean }> = [
    { kind: 'input', label: '输入', detail: '文字 + 多附件/文件夹 · 兼容旧资料节点', icon: ArrowUpFromLine },
    { kind: 'analyzer', label: 'CLI 分析器', detail: 'Agent · 模型 · Skill', icon: Sparkles },
    { kind: 'condition', label: '条件分支', detail: '字段 · 比较 · 路由', icon: GitBranch },
    { kind: 'filter', label: '输入过滤器', detail: '名称 glob/regex · 格式 AND', icon: Filter },
    { kind: 'human', label: '人工确认', detail: '审批 · 备注 · 继续', icon: ClipboardCheck },
    { kind: 'blackbox', label: '黑盒子', detail: '可进入编辑的子流程', icon: Boxes },
    { kind: 'blackbox', loop: true, label: '有界循环', detail: '执行器 · 审阅器 · 有界轮数', icon: RefreshCw },
    { kind: 'blackbox', loop: true, humanGate: true, label: '有界循环（人工审阅）', detail: '明确启用 reviewer 后人工闸门', icon: ClipboardCheck },
    { kind: 'container', label: '授权输出', detail: '文件 · JSON · 溯源', icon: Archive },
  ]
  return (
    <aside className="left-panel panel-surface">
      <div className="panel-heading"><div><span className="eyebrow">BUILDING BLOCKS</span><h2>组件库</h2></div><button className="icon-button" onClick={onClose} title="收起组件库"><PanelLeft size={16} /></button></div>
      <p className="panel-intro">把研究过程拆成一条能回看的资料链。</p>
      <button className="upload-button" onClick={onUpload}><Upload size={16} />导入资料</button>
      <button className="upload-button folder-upload-button" title="选择文件夹后，会把目录内文件逐个导入画布" onClick={onUploadFolder}><FolderOpen size={16} />导入资料文件夹</button>
      <div className="library-list">
        {entries.map(({ kind, label, detail, icon: Icon, loop, humanGate }) => (
          <button key={`${kind}-${loop ? 'loop' : 'normal'}-${humanGate ? 'human' : 'auto'}`} className="library-item" draggable={canAddNodes} disabled={!canAddNodes} title={canAddNodes ? `新增${label}` : '正在加载全局默认设置，请稍候'} onDragStart={(event) => { event.dataTransfer.setData('application/x-kxy-node', kind); event.dataTransfer.setData('application/x-kxy-node-options', JSON.stringify({ loop: Boolean(loop), humanGate: Boolean(humanGate) })) }} onClick={() => onAdd(kind, loop, humanGate)}>
            <span className={`library-icon ${toneForKind[kind]}`}><Icon size={17} /></span>
            <span><strong title={label}>{label}</strong><small title={detail}>{detail}</small></span>
            <Plus size={15} className="library-plus" />
          </button>
        ))}
      </div>
      <div className="panel-divider" />
      <SectionTitle icon={BookOpen} action={<button className="text-button" disabled={skillMutationBusy} onClick={onImportSkill}>导入</button>}>技能挂载</SectionTitle>
      <div className="skill-library-toolbar">
        <label className="skill-select-all"><input type="checkbox" aria-label="全选技能" checked={skillSelectionComplete} disabled={skills.length === 0 || skillMutationBusy} onChange={() => setSelectedSkillIds(skillSelectionComplete ? [] : skills.map((skill) => skill.id))} /><span>全选</span></label>
        <button className="text-button" type="button" disabled={skills.length === 0 || skillMutationBusy} onClick={() => setSelectedSkillIds(skills.filter((skill) => !selectedSkillIds.includes(skill.id)).map((skill) => skill.id))}>反选</button>
        <span className="skill-selection-count">已选 {selectedSkillIds.length} / {skills.length}</span>
        <button className="mini-button skill-bulk-delete" type="button" disabled={selectedSkillIds.length === 0 || skillMutationBusy} onClick={() => { void deleteSelectedSkills().catch(() => undefined) }} title="删除当前选择的 KXY 技能记录与快照；保留 Agent 原始目录、中央库和历史运行"><Trash2 size={12} />{bulkDeleteBusy ? '删除中' : '批量删除'}</button>
      </div>
      <div className="skill-list">
        {skills.length === 0 ? <div className="empty-note">尚未挂载本地技能。导入只做快照，不执行其中代码。</div> : skills.map((skill) => {
          const selected = selectedSkillIds.includes(skill.id)
          return <div className={`skill-pill ${selected ? 'selected' : ''}`} key={skill.id} title={skill.name}>
            <input type="checkbox" aria-label={`选择技能 ${skill.name}`} checked={selected} disabled={skillMutationBusy} onChange={() => setSelectedSkillIds((current) => selected ? current.filter((id) => id !== skill.id) : [...current, skill.id])} />
            <ShieldCheck size={13} /><span>{skill.name}</span><small>{skill.snapshot_hash.slice(0, 8)}</small>
            <button className="skill-delete" type="button" disabled={skillMutationBusy} title="删除技能快照" onClick={() => onDeleteSkill(skill.id)}><X size={12} /></button>
          </div>
        })}
      </div>
      <div className="skillhub-index-card" data-testid="skillhub-index-card">
        <div className="skillhub-index-heading">
          <div><span className="field-caption">SKILLHUB INDEX</span><strong>中央索引同步</strong></div>
          <button className="icon-button" type="button" aria-label="扫描 SkillHub 中央索引" title="只读扫描中央索引和副本" onClick={onScanSkillHub} disabled={skillMutationBusy}>{skillHubScanBusy ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}</button>
        </div>
        <p className="skillhub-index-help">只读比较 KXY 本地快照与中央索引和副本。默认不选择任何修复、纳入或恢复动作。</p>
        {!skillHubScan ? <div className="skillhub-index-empty">点击扫描，查看可修复映射、待纳入副本和显式恢复项。</div> : <>
          <div className="skillhub-counts">{Object.entries(skillHubScan.counts).sort(([left], [right]) => left.localeCompare(right)).map(([status, count]) => <span className={`skillhub-count skillhub-status-${status}`} key={status}>{skillHubStatusLabels[status] || status} {count}</span>)}</div>
          {normalIndexItems.length > 0 && <div className="skillhub-sync-group">
            <div className="skillhub-sync-heading"><span>普通更新</span><button className="text-button" type="button" disabled={skillMutationBusy} onClick={selectNormalIndexItems}>{normalSelectionComplete ? '清空普通选择' : '全选普通更新'}</button></div>
            {normalIndexItems.map((item) => {
              const action: SkillHubSyncAction = item.status === 'repairable' ? 'repair' : 'add'
              const selected = selectedIndexActions[item.key] === action
              return <label className={`skillhub-sync-row ${selected ? 'selected' : ''}`} key={item.key}>
                <input type="checkbox" aria-label={`${skillHubActionLabels[action]} ${item.name}`} checked={selected} disabled={skillMutationBusy} onChange={() => toggleIndexAction(item, action)} />
                <span><strong>{item.name}</strong><small>{skillHubActionLabels[action]} · {item.upstream_skill_id || item.key}</small>{item.reason && <em>{item.reason}</em>}</span>
              </label>
            })}
          </div>}
          {restoreIndexItems.length > 0 && <div className="skillhub-sync-group skillhub-restore-group">
            <div className="skillhub-sync-heading"><span>恢复项（需单独选择）</span><small>不会被全选普通更新带入</small></div>
            {restoreIndexItems.map((item) => {
              const selected = selectedIndexActions[item.key] === 'restore'
              return <label className={`skillhub-sync-row ${selected ? 'selected restore' : 'restore'}`} key={item.key}>
                <input type="checkbox" aria-label={`明确恢复 ${item.name}`} checked={selected} disabled={skillMutationBusy} onChange={() => toggleIndexAction(item, 'restore')} />
                <span><strong>{item.name}</strong><small>{skillHubActionLabels.restore} · 将恢复原 KXY id</small>{item.reason && <em>{item.reason}</em>}</span>
              </label>
            })}
          </div>}
          {(() => {
            const blocked = (skillHubScan.items || []).filter((item) => item.actions.length === 0 && !['unchanged'].includes(item.status))
            return blocked.length > 0 ? <details className="skillhub-blocked"><summary>阻塞或待处理 {blocked.length} 项</summary>{blocked.map((item) => <div className="skillhub-blocked-row" key={item.key}><strong>{item.name}</strong><small>{skillHubStatusLabels[item.status] || item.status} · {item.reason || '需要重新检查'}</small></div>)}</details> : null
          })()}
          <div className="skillhub-sync-footer"><span>{selectedIndexCount > 0 ? `已选 ${selectedIndexCount} 项` : '未选择同步动作'}</span><button className="outline-button compact-button" type="button" disabled={selectedIndexCount === 0 || skillMutationBusy} onClick={() => { void syncSelectedIndexItems().catch(() => undefined) }}>{skillHubSyncBusy ? <LoaderCircle size={12} className="spin" /> : <Check size={12} />}同步选中</button></div>
        </>}
      </div>
      <SectionTitle icon={LayoutTemplate} action={<button className="mini-button" type="button" aria-label="切换预设排序" onClick={() => setPresetSort((value) => value === 'date' ? 'name' : 'date')}>{presetSort === 'date' ? '最新日期' : '名称排序'}</button>}>组件预设</SectionTitle>
      <div className="preset-toolbar"><span>按组件类别分组</span><small>{presetSort === 'date' ? '组内按最新修改' : '组内按名称'}</small></div>
      <div className="preset-list">
        {presets.length === 0 ? <div className="empty-note">选中一个组件后，可在右侧保存为命名预设。</div> : [...new Set(presets.map((item) => item.kind))].sort().map((kind) => {
          const group = presets.filter((item) => item.kind === kind).sort((left, right) => {
            if (presetSort === 'name') return left.name.localeCompare(right.name, 'zh-Hans-CN')
            return String(right.updated_at || right.created_at || '').localeCompare(String(left.updated_at || left.created_at || ''))
          })
          return <section className="preset-group" key={kind}><div className="preset-group-heading"><strong>{presetKindLabels[kind]}</strong><small>{group.length} 项</small></div>{group.map((preset) => {
            const presetKey = `${preset.source || 'component'}:${preset.id}`
            const expanded = expandedPresetId === presetKey
            const missing = presetMissingReferences(preset, files, skills, models, grants, credentials, mcps)
            return <div key={presetKey} className={`preset-item ${expanded ? 'expanded' : ''}`}>
              <div className="preset-item-heading">
                <button className="preset-expand" type="button" aria-expanded={expanded} aria-controls={`preset-config-${presetKey}`} onClick={() => setExpandedPresetId((current) => current === presetKey ? null : presetKey)}><ChevronDown size={13} /><span title={preset.name}>{preset.name}</span><small>{expanded ? '收起配置' : '展开配置'}</small></button>
                <button className="preset-apply" type="button" disabled={missing.length > 0} title={missing.length > 0 ? `缺少本机引用：${missing.join('、')}` : `应用${presetKindLabels[preset.kind]}预设`} onClick={() => onApplyPreset(preset)}><Check size={12} />应用</button>
                <button className="preset-delete" type="button" title={`删除${presetKindLabels[preset.kind]}预设`} onClick={() => onDeletePreset(preset)}><Trash2 size={12} /></button>
              </div>
              {missing.length > 0 && <small className="preset-missing" title={missing.join('、')}>缺少本机引用：{missing.join('、')}</small>}
              {expanded && <div id={`preset-config-${presetKey}`} className="preset-details"><div className="field-caption">已保存配置（敏感字段已隐藏）</div><pre>{JSON.stringify(stripPresetValue(preset.config), null, 2)}</pre></div>}
            </div>
          })}</section>
        })}
      </div>
    </aside>
  )
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="form-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

function collectTransportAttribution(value: unknown): string {
  const seen = new Set<string>()
  const parts: string[] = []
  const visit = (candidate: unknown) => {
    if (Array.isArray(candidate)) {
      candidate.forEach(visit)
      return
    }
    if (!candidate || typeof candidate !== 'object') return
    const item = candidate as Record<string, unknown>
    for (const field of [item.node_path, item.cli, item.model_alias || item.model]) {
      if (typeof field !== 'string' || !field.trim() || seen.has(field)) continue
      seen.add(field)
      parts.push(field)
    }
    for (const key of ['items', 'upstream', 'inputs']) visit(item[key])
  }
  visit(value)
  return parts.join(' · ')
}

function flattenSampleFields(value: unknown, prefix = '', result = new Set<string>(), depth = 0): string[] {
  if (depth > 4 || !value || typeof value !== 'object' || Array.isArray(value)) return [...result]
  Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    result.add(path)
    if (child && typeof child === 'object' && !Array.isArray(child)) flattenSampleFields(child, path, result, depth + 1)
  })
  return [...result].sort()
}

const GENERATED_FILE_EXTENSIONS = ['.txt', '.md', '.json', '.csv', '.pdf', '.docx', '.xlsx', '.pptx', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.html', '.mp4', '.avi', '.zip'] as const

function InspectorPanel({
  node,
  run,
  outputPath,
  files,
  skills,
  grants,
  agents,
  models,
  mcps,
  onUpdate,
  onDelete,
  onSavePreset,
  onAuthorize,
  onRevoke,
  onEnterBlackbox,
  onUnpackBlackbox,
  onPreviewSkillMount,
  onCheckSkillDependencies,
  onSetSkillDependencies,
  autoCheckMounts,
  onUploadAttachment,
  onUploadAttachmentFolder,
  conditionSample,
  filterItems,
  onOpenSettings,
  onClose,
}: {
  node: KxyNode | undefined
  run?: Run | null
  outputPath?: string
  files: FileAsset[]
  skills: Skill[]
  grants: Array<{ id: string; canonical_path: string; revoked_at?: string | null }>
  agents: AgentProfile[]
  models: AgentModel[]
  mcps: McpRecord[]
  onUpdate: (patch: Partial<KxyNodeData>) => void
  onDelete: () => void
  onSavePreset: () => void
  onAuthorize: () => void
  onRevoke: (id: string) => void
  onEnterBlackbox: () => void
  onUnpackBlackbox: () => void
  onPreviewSkillMount: (agentId: string, skillIds: string[]) => Promise<{ status?: string; skills?: Array<{ skill_id?: string; status?: string; message?: string; cross_agent?: boolean }> }>
  onCheckSkillDependencies: (payload: { agent_id: string; skill_ids: string[]; force?: boolean; model_ref?: string; credential_id?: string; model?: string; source?: string; mcp_ids?: string[] }) => Promise<DependencyCheckResponse>
  onSetSkillDependencies: (skillId: string, dependencies: Record<string, unknown>) => Promise<DependencySkillResult>
  autoCheckMounts: boolean
  onUploadAttachment: () => void
  onUploadAttachmentFolder: () => void
  conditionSample?: { source: string; value: unknown; fields: string[] }
  filterItems?: unknown[]
  onOpenSettings: () => void
  onClose: () => void
}) {
  const [mountPreview, setMountPreview] = useState<{ tone: 'idle' | 'loading' | 'ok' | 'error'; text: string }>({ tone: 'idle', text: '' })
  const [schemaText, setSchemaText] = useState('')
  const [schemaMessage, setSchemaMessage] = useState<{ tone: 'idle' | 'ok' | 'error'; text: string }>({ tone: 'idle', text: '' })
  const [filterPreview, setFilterPreview] = useState<{ tone: 'idle' | 'loading' | 'ok' | 'error'; text: string }>({ tone: 'idle', text: '' })
  const [skillExpanded, setSkillExpanded] = useState(true)
  const [mcpExpanded, setMcpExpanded] = useState(true)
  const [skillSearch, setSkillSearch] = useState('')
  const [mcpSearch, setMcpSearch] = useState('')
  const [dependencyCheck, setDependencyCheck] = useState<DependencyCheckResponse | null>(null)
  const [dependencyCheckError, setDependencyCheckError] = useState<string | null>(null)
  const [dependencyCheckBusy, setDependencyCheckBusy] = useState(false)
  const [dependencyEditSkillId, setDependencyEditSkillId] = useState('')
  const [dependencyDrafts, setDependencyDrafts] = useState<Record<string, string>>({})
  const [dependencyEditMessage, setDependencyEditMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const [dependencyEditBusy, setDependencyEditBusy] = useState(false)
  const schemaInputRef = useRef<HTMLInputElement>(null)
  const dependencyGenerationRef = useRef(0)
  useEffect(() => {
    const schema = node?.data.output_schema
    setSchemaText(schema && typeof schema === 'object' ? JSON.stringify(schema, null, 2) : '')
    setSchemaMessage({ tone: 'idle', text: '' })
    setFilterPreview({ tone: 'idle', text: '' })
  }, [node?.id, node?.data.output_schema])
  const currentData = node?.data
  const currentSkillIds = currentData?.skill_ids || []
  const currentMcpIds = currentData?.mcp_ids || []
  const currentAgentProfile = agents.find((item) => item.id === (currentData?.cli || 'codex'))
  const currentModelProfile = models.find((item) => item.id === currentData?.model_ref && (item.cli_id === currentData?.cli || item.agent_id === currentData?.cli || item.cli_id === '*'))
  const runtimeScope = [
    currentAgentProfile?.executable || '',
    currentAgentProfile?.runtime_interpreter || currentAgentProfile?.runtime?.interpreter || '',
    currentAgentProfile?.runtime?.interpreter_version || '',
    currentAgentProfile?.runtime?.version || '',
    currentAgentProfile?.runtime?.status || '',
  ].join('|')
  const modelScope = currentModelProfile
    ? [currentModelProfile.id, currentModelProfile.cli_id, currentModelProfile.agent_id || '', currentModelProfile.model, currentModelProfile.source, currentModelProfile.credential_id || '', (currentModelProfile.efforts || []).join(','), currentModelProfile.default_effort || ''].join('|')
    : ''
  const dependencyScopeKey = node
    ? `${node.id}|${currentData?.cli || 'codex'}|${runtimeScope}|${modelScope}|${currentData?.model_ref || ''}|${currentData?.credential_id || ''}|${[...currentSkillIds].sort().join(',')}|${[...currentMcpIds].sort().join(',')}`
    : 'empty'
  useEffect(() => {
    if (!currentSkillIds.includes(dependencyEditSkillId)) setDependencyEditSkillId(currentSkillIds[0] || '')
  }, [node?.id, currentSkillIds.join(','), dependencyEditSkillId])
  const runDependencyCheck = async (force = false, skillIds = currentSkillIds) => {
    const generation = dependencyGenerationRef.current + 1
    dependencyGenerationRef.current = generation
    if (!node || !currentData || !skillIds.length) {
      setDependencyCheck(null)
      setDependencyCheckError(null)
      return
    }
    setDependencyCheckBusy(true)
    setDependencyCheckError(null)
    try {
      const result = await onCheckSkillDependencies({
        agent_id: currentData.cli || 'codex',
        skill_ids: skillIds,
        force,
        ...(currentData.model_ref ? { model_ref: currentData.model_ref } : {}),
        ...(currentData.credential_id ? { credential_id: currentData.credential_id } : {}),
        ...(currentData.model ? { model: currentData.model } : {}),
        mcp_ids: currentMcpIds,
      })
      if (generation === dependencyGenerationRef.current) setDependencyCheck(result)
      return result
    } catch (error) {
      if (generation === dependencyGenerationRef.current) setDependencyCheckError(error instanceof Error ? error.message : String(error))
      return null
    } finally {
      if (generation === dependencyGenerationRef.current) setDependencyCheckBusy(false)
    }
  }
  const saveDependencyDeclaration = async () => {
    const skillId = dependencyEditSkillId
    if (!skillId) return
    const raw = dependencyDrafts[skillId] ?? JSON.stringify(dependencyCheck?.skills.find((item) => item.skill_id === skillId)?.declared_dependencies || {}, null, 2)
    let dependencies: Record<string, unknown>
    try {
      const parsed = JSON.parse(raw || '{}') as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('依赖声明必须是 JSON 对象')
      dependencies = parsed as Record<string, unknown>
    } catch (error) {
      setDependencyEditMessage({ tone: 'error', text: error instanceof Error ? error.message : '依赖声明 JSON 无效' })
      return
    }
    setDependencyEditBusy(true)
    setDependencyEditMessage(null)
    try {
      const result = await onSetSkillDependencies(skillId, dependencies)
      setDependencyDrafts((current) => ({ ...current, [skillId]: JSON.stringify(result.declared_dependencies || dependencies, null, 2) }))
      setDependencyEditMessage({ tone: 'ok', text: '依赖声明已保存；正在按当前 Agent runtime 重新检查。' })
      await runDependencyCheck(true, currentSkillIds)
    } catch (error) {
      setDependencyEditMessage({ tone: 'error', text: error instanceof Error ? error.message : String(error) })
    } finally {
      setDependencyEditBusy(false)
    }
  }
  useEffect(() => {
    dependencyGenerationRef.current += 1
    setDependencyCheck(null)
    setDependencyCheckError(null)
    setDependencyCheckBusy(false)
    if (node && currentData?.kind === 'analyzer' && autoCheckMounts && currentSkillIds.length > 0) void runDependencyCheck(false, currentSkillIds)
    // The scope key intentionally includes node, Agent, model binding and the
    // selected Skill/MCP set so a late response cannot overwrite a new scope.
  }, [dependencyScopeKey, autoCheckMounts])
  if (!node) return <aside className="right-panel panel-surface"><div className="panel-heading"><div><span className="eyebrow">WORKSPACE</span><h2>工作台</h2></div><button className="icon-button" onClick={onClose} title="收起检查器"><PanelRight size={16} /></button></div><div className="inspector-scroll"><div className="inspector-empty compact"><div className="empty-orbit"><Palette size={20} /></div><h3>外观设置已集中到全局面板</h3><p>字体、字号、背景图、动效与撤回深度只在一个地方保存。</p><button className="run-button full-width" onClick={onOpenSettings}><Settings2 size={14} />打开全局设置</button></div><div className="panel-divider" /><div className="inspector-empty compact"><div className="empty-orbit"><Workflow size={20} /></div><h3>选中一个节点</h3><p>在画布中选择节点，调整输入、CLI、条件和输出授权。</p></div></div></aside>
  const data = node.data
  const kind = data.kind || (node.type as NodeKind) || 'text'
  const selectedSkillIds = data.skill_ids || []
  const selectedMcpIds = data.mcp_ids || []
  const skillTerm = skillSearch.trim().toLocaleLowerCase()
  const mcpTerm = mcpSearch.trim().toLocaleLowerCase()
  const visibleSkills = skills.filter((skill) => !skillTerm || skill.name.toLocaleLowerCase().includes(skillTerm))
  const visibleMcps = mcps.filter((mcp) => !mcpTerm || mcp.name.toLocaleLowerCase().includes(mcpTerm))
  const selectedSkillCount = skills.filter((skill) => selectedSkillIds.includes(skill.id)).length
  const selectedMcpCount = mcps.filter((mcp) => selectedMcpIds.includes(mcp.id)).length
  const file = files.find((item) => item.id === data.file_id)
  const innerAnalyzers = (data.workflow?.nodes || []).filter((item) => item.type === 'analyzer')
  const loopSeed = { ...defaultLoopConfig(innerAnalyzers[0]?.id || '', innerAnalyzers[1]?.id || innerAnalyzers[0]?.id || ''), enabled: data.loop?.enabled === true }
  const loopConfig: LoopConfig = {
    ...loopSeed,
    ...(data.loop || {}),
    executor_id: data.loop?.executor_id || loopSeed.executor_id,
    reviewer_id: data.loop?.reviewer_id || loopSeed.reviewer_id,
    review_fields: { ...loopSeed.review_fields, ...(data.loop?.review_fields || {}) },
    feedback: { ...loopSeed.feedback, ...(data.loop?.feedback || {}) },
  }
  const updateLoop = (patch: Omit<Partial<LoopConfig>, 'review_fields' | 'feedback'> & { review_fields?: Partial<LoopReviewFields>; feedback?: Partial<LoopFeedback> }) => onUpdate({ loop: { ...loopConfig, ...patch, review_fields: { ...loopConfig.review_fields, ...(patch.review_fields || {}) }, feedback: { ...loopConfig.feedback, ...(patch.feedback || {}) } } })
  const agent = agents.find((item) => item.id === data.cli)
  const selectedModel = models.find((item) => item.id === data.model_ref && (item.cli_id === data.cli || item.agent_id === data.cli || item.cli_id === '*'))
  const modelOptions = models.filter((item) => (item.cli_id === data.cli || item.agent_id === data.cli || item.cli_id === '*') && (item.source !== 'native' || Boolean(item.native_model_ref) || item.id === data.model_ref))
  const configuredAgentOptions = models.filter((item) => (item.source !== 'native' || Boolean(item.native_model_ref) || item.id === data.model_ref) && item.cli_id !== '*')
  const analyzerSelection = selectedModel ? `model:${selectedModel.id}` : `cli:${data.cli || 'codex'}`
  const effortOptions = selectedModel ? (selectedModel.efforts || []) : []
  const effectiveEffort = data.effort || data.variant || selectedModel?.default_effort || ''
  const nodeTypeLabel = kind === 'file' ? '资料节点' : kind === 'analyzer' ? 'CLI 分析器' : kind === 'condition' ? '条件分支' : kind === 'filter' ? '输入过滤器' : kind === 'container' ? '授权输出' : kind === 'human' ? '人工确认' : kind === 'blackbox' ? '黑盒子' : kind === 'subflow_input' ? '子流程输入' : kind === 'subflow_output' ? '子流程输出' : '输入'
  const selectAnalyzer = (value: string) => {
    if (value.startsWith('model:')) {
      const model = models.find((item) => item.id === value.slice('model:'.length))
      if (!model) return
      const cli = model.cli_id === '*' ? data.cli || 'codex' : model.cli_id
      onUpdate({ cli, agent_id: model.agent_id || cli, model_ref: model.id, model: '', credential_id: '', variant: '', effort: model.default_effort || '' })
      return
    }
    const cli = value.startsWith('cli:') ? value.slice('cli:'.length) : value
    onUpdate({ cli, agent_id: cli, model: '', model_ref: '', credential_id: '', variant: '', effort: '' })
  }
  const selectModel = (value: string) => {
    const model = models.find((item) => item.id === value)
    if (!value) {
      onUpdate({ model_ref: '', model: '', credential_id: '', variant: '', effort: '' })
      return
    }
    const cli = model?.cli_id || data.cli || 'codex'
    onUpdate({ cli, agent_id: model?.agent_id || cli, model_ref: value, model: '', credential_id: '', variant: '', effort: model?.default_effort || '' })
  }
  const parseSchemaText = (): Record<string, unknown> | null => {
    if (!schemaText.trim()) return null
    try {
      const parsed = JSON.parse(schemaText) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Schema 必须是 JSON 对象')
      if (new TextEncoder().encode(JSON.stringify(parsed)).byteLength > 200_000) throw new Error('Schema 超过 200 KB')
      let remoteRef = false
      const inspect = (value: unknown) => {
        if (Array.isArray(value)) value.forEach(inspect)
        else if (value && typeof value === 'object') Object.entries(value).forEach(([key, item]) => {
          if (['$ref', '$dynamicRef', '$recursiveRef'].includes(key) && (typeof item !== 'string' || !item.startsWith('#'))) remoteRef = true
          inspect(item)
        })
      }
      inspect(parsed)
      if (remoteRef) throw new Error('只允许本地 #/$ref，不能访问远程 Schema')
      return parsed as Record<string, unknown>
    } catch (error) {
      setSchemaMessage({ tone: 'error', text: error instanceof Error ? error.message : 'Schema JSON 无效' })
      return null
    }
  }
  const validateSchema = () => {
    const parsed = parseSchemaText()
    if (schemaText.trim() && !parsed) return
    setSchemaMessage({ tone: 'ok', text: parsed ? 'Schema JSON 与本地引用检查通过；运行前后端还会校验 Schema 规范。' : '未设置 Schema；JSON 输出仍会要求对象。' })
  }
  const applySchema = () => {
    const parsed = parseSchemaText()
    if (schemaText.trim() && !parsed) return
    onUpdate({ output_schema: parsed || undefined })
    setSchemaMessage({ tone: 'ok', text: parsed ? 'Schema 已应用到当前分析器。' : 'Schema 已清除。' })
  }
  const exportSchema = () => {
    const parsed = parseSchemaText()
    if (schemaText.trim() && !parsed) return
    const content = JSON.stringify(parsed || {}, null, 2)
    const url = URL.createObjectURL(new Blob([content], { type: 'application/schema+json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'kxy-output-schema.json'; anchor.click(); URL.revokeObjectURL(url)
    setSchemaMessage({ tone: 'ok', text: 'Schema 已校验并导出；无效内容不会伪装成 Schema 文件。' })
  }
  const importSchema = (file: File) => {
    void file.text().then((content) => {
      setSchemaText(content)
      setSchemaMessage({ tone: 'idle', text: 'Schema 已载入编辑器；点击应用前不会改变流程。' })
    }).catch(() => setSchemaMessage({ tone: 'error', text: 'Schema 文件读取失败' }))
  }
  const outputFormat: OutputFormat = data.output_format || (data.expect_json ? 'json' : 'auto')
  const containerFormats: ReplyExportFormat[] = Array.isArray(data.export_formats) ? data.export_formats : ['markdown', 'json']
  const hasFileAllowlist = Array.isArray(data.allowed_file_extensions)
  const allowedFileExtensions = hasFileAllowlist ? data.allowed_file_extensions || [] : []
  const containerOutputKeys = outputPath ? Array.from(new Set([outputPath, run?.nodes?.find((item) => item.node_path === outputPath)?.node_id].filter((value): value is string => Boolean(value)))) : []
  const containerOutputCandidates = kind === 'container' && run?.output_manifest?.outputs && outputPath
    ? containerOutputKeys.map((key) => run.output_manifest!.outputs![key])
    : []
  const containerOutputValue = containerOutputCandidates.find((value) => value && typeof value === 'object' && !Array.isArray(value) && ('export_formats' in value || 'artifact_count' in value))
  const containerOutputRecord = containerOutputValue && typeof containerOutputValue === 'object' && !Array.isArray(containerOutputValue) ? containerOutputValue as Record<string, unknown> : null
  const containerReplyValue = containerOutputRecord?.text ?? containerOutputRecord?.content
  const containerReplyText = typeof containerReplyValue === 'string' ? containerReplyValue : containerReplyValue === undefined ? '' : JSON.stringify(containerReplyValue, null, 2)
  const containerAttribution = containerOutputRecord ? collectTransportAttribution(containerOutputRecord) : ''
  const containerHasArtifacts = Boolean(containerOutputRecord && ((Array.isArray(containerOutputRecord.artifacts) && containerOutputRecord.artifacts.length > 0) || Number(containerOutputRecord.artifact_count || 0) > 0))
  const containerReplyLabel = containerReplyText.trim() ? '来自运行记录' : containerHasArtifacts ? '本次仅生成文件' : run ? '尚无正文回复' : '运行后显示'
  const containerReplyPlaceholder = containerHasArtifacts ? '（无正文回复；本次运行仅生成文件）' : run ? '（尚无正文回复）' : '运行这个流程后，正文回复会显示在这里。'
  const insertWorkspaceHint = () => {
    const current = String(data.prompt || '')
    if (current.includes('input-context.json')) return
    onUpdate({ prompt: current ? `${current}\n\n${WORKSPACE_PROMPT_HINT}` : WORKSPACE_PROMPT_HINT })
  }
  const updateReplyFormats = (mode: 'all' | 'invert') => {
    const all: ReplyExportFormat[] = ['markdown', 'text', 'json']
    onUpdate({ export_formats: mode === 'all' ? all : all.filter((format) => !containerFormats.includes(format)) })
  }
  const updateGeneratedFileExtensions = (mode: 'all' | 'invert') => {
    const all = [...GENERATED_FILE_EXTENSIONS]
    onUpdate({ allowed_file_extensions: mode === 'all' ? all : all.filter((extension) => !allowedFileExtensions.includes(extension)) })
  }
  return (
    <aside className="right-panel panel-surface">
      <div className="panel-heading"><div><span className="eyebrow">INSPECTOR</span><h2>节点设置</h2></div><div className="run-actions"><button className="icon-button" onClick={onClose} title="收起检查器"><PanelRight size={15} /></button><button className="danger-icon" onClick={onDelete} title="删除节点"><Trash2 size={16} /></button></div></div>
      <div className={`inspector-type ${toneForKind[kind]}`}><span className="library-icon"><>{(() => { const Icon = iconForKind[kind]; return <Icon size={17} /> })()}</></span><span>{nodeTypeLabel}</span><code title={node.id}>{node.id}</code></div>
      <div className="inspector-scroll">
        <Field label="节点名称"><input value={data.label || ''} onChange={(event) => onUpdate({ label: event.target.value })} /></Field>
        {(kind === 'text' || kind === 'input') && <Field label="输入内容" hint={kind === 'input' ? '文字与附件可以同时存在；附件只保存 file_id 和显示/匹配路径。' : '为后续分析器提供问题、说明或资料'}><textarea rows={8} value={data.text || ''} onChange={(event) => onUpdate({ text: event.target.value })} /></Field>}
        {kind === 'input' && <div className="input-attachments-card"><div className="settings-card-heading"><div><span className="field-caption">ATTACHMENTS</span><strong>本输入的附件</strong></div><span className="settings-count">{(data.attachments || []).length} 项</span></div><div className="approval-actions"><button className="mini-button" type="button" onClick={onUploadAttachment}><Upload size={12} />追加文件</button><button className="mini-button" type="button" onClick={onUploadAttachmentFolder}><FolderOpen size={12} />追加文件夹</button></div>{(data.attachments || []).length === 0 ? <small className="empty-note">尚未选择附件；旧 file_id 仍会兼容显示。</small> : <div className="attachment-list">{(data.attachments || []).map((attachment, index) => { const asset = files.find((item) => item.id === attachment.file_id); return <div className="attachment-row" key={attachment.file_id + '-' + index}><FileText size={13} /><span title={attachment.relative_path || attachment.display_name}>{attachment.relative_path || attachment.display_name || asset?.display_name || attachment.file_id}</span><small>{asset ? asset.status + ' · ' + Math.round(asset.size / 1024) + ' KB' : '缺少本机引用'}</small><button className="mini-button" type="button" onClick={() => { const next = (data.attachments || []).filter((_, itemIndex) => itemIndex !== index); onUpdate({ attachments: next, file_ids: next.map((item) => item.file_id) }) }}><X size={12} />移除</button></div> })}</div>}<small className="helper-copy">选择文件夹会合并成一张输入卡；relative_path 只用于显示和过滤匹配，不会被当作本机路径读取。</small></div>}
        {kind === 'file' && <div className="file-inspector"><div className="file-line"><FileText size={17} /><div><strong title={file?.display_name || data.fileName || '等待上传'}>{file?.display_name || data.fileName || '等待上传'}</strong><small>{file ? `${file.status} · ${Math.round(file.size / 1024)} KB` : '将文件拖到画布或点击左侧导入'}</small></div></div>{file?.preview && <pre>{file.preview.slice(0, 1200)}</pre>}{file && <a href={`${API}/api/files/${file.id}/content`} target="_blank" rel="noreferrer" className="inline-link">打开原始文件 <ArrowUpFromLine size={13} /></a>}</div>}
        {kind === 'analyzer' && <>
          <Field label="分析提示词" hint="会直接传给选择的 Agent；凭据只在全局设置中配置"><textarea rows={9} value={data.prompt || ''} onChange={(event) => onUpdate({ prompt: event.target.value })} /></Field>
          <div className="workspace-hint-card"><div><span className="field-caption">WORKSPACE ACCESS</span><strong>输入与技能说明</strong></div><button className="mini-button" type="button" onClick={insertWorkspaceHint}><CornerDownLeft size={12} />插入工作区提示</button><small>只把可见文本写入上方提示词，运行时不会隐式追加；可继续修改或删除。</small></div>
          <div className="two-fields"><Field label="Agent / CLI"><select title={selectedModel ? `${selectedModel.model} · ${selectedModel.alias} · ${selectedModel.default_effort || 'Agent 默认'}` : `${agent?.label || data.cli || 'codex'} · CLI 默认`} value={analyzerSelection} onChange={(event) => selectAnalyzer(event.target.value)}><optgroup label="CLI 默认">{agents.map((item) => <option key={item.id} value={`cli:${item.id}`} title={item.label}>{item.label}{item.available ? '' : ' · 不可用'}</option>)}</optgroup><optgroup label="已配置分析器">{configuredAgentOptions.map((model) => <option key={model.id} value={`model:${model.id}`} title={`${model.model} · ${model.alias} · ${model.default_effort || 'Agent 默认'}`}>{agents.find((item) => item.id === (model.agent_id || model.cli_id))?.label || model.cli_id} · {model.model} · {model.alias} · {model.default_effort || 'Agent 默认'}</option>)}</optgroup></select></Field><Field label="effort"><select value={effectiveEffort} onChange={(event) => onUpdate({ effort: event.target.value })}><option value="">Agent 默认</option>{effectiveEffort && !effortOptions.includes(effectiveEffort) && <option value={effectiveEffort}>{effectiveEffort} · 当前记录不再支持</option>}{effortOptions.map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></Field></div>
          <Field label="模型记录" hint="只选择已保存的模型配置；配置删除后会保留明确的未绑定状态"><select title={selectedModel ? `${selectedModel.model} · ${selectedModel.alias}` : data.model_ref ? '已绑定模型不可用 · 需重新绑定' : '使用 Agent 默认模型'} value={data.model_ref || ''} onChange={(event) => selectModel(event.target.value)}><option value="">使用 Agent 默认模型</option>{data.model_ref && !modelOptions.some((item) => item.id === data.model_ref) && <option value={data.model_ref}>已绑定模型不可用 · 需重新绑定</option>}{modelOptions.map((model) => <option key={model.id} value={model.id} title={`${model.model} · ${model.alias}`}>{model.model} · {model.alias} · {model.native_model_ref ? '登录态（本机 CLI）' : model.source === 'api' ? 'API' : model.source === 'native' ? '原生目录' : '兼容配置'}</option>)}</select></Field>
          {data.model && !data.model_ref && <div className="migration-note">旧流程仍带有模型标识 “{data.model}”；它不会被静默替换。请在全局模型设置中创建/绑定记录。</div>}
          <div className="two-fields"><Field label="超时（秒）"><input type="number" min={5} max={3600} value={data.timeout || 600} onChange={(event) => onUpdate({ timeout: Number(event.target.value) })} /></Field><label className="check-field"><input type="checkbox" checked={Boolean(data.network)} onChange={(event) => onUpdate({ network: event.target.checked })} /><span>允许网络</span><small>{data.network ? '允许连接模型和公开网站' : '关闭网络；不可强制时运行会失败'}</small></label></div>
          <Field label="输出格式" hint="自动保留 Agent 原文；JSON 只做本地对象/Schema 验证，提示词需由你明确要求 JSON">
            <select value={outputFormat} onChange={(event) => { const value = event.target.value as OutputFormat; onUpdate({ output_format: value, expect_json: value === 'json', ...(value === 'json' ? {} : { output_schema: undefined }) }) }}>
              <option value="auto" title="保留 Agent 返回的原文；若原文确实是对象 JSON，额外提供结构化路由。">自动（按提示词）</option><option value="markdown" title="仅作为本地输出文件扩展名约定；不会修改传给 Agent 的提示词。">Markdown</option><option value="text" title="仅作为本地输出文件扩展名约定；不会修改传给 Agent 的提示词。">纯文本</option><option value="json" title="必须是单个合法 JSON 对象；可用本地 JSON Schema 校验，提示词需自行要求 JSON。">JSON 对象</option>
            </select>
          </Field>
          <div className="output-format-help"><strong>{outputFormat === 'json' ? 'JSON 验证模式' : outputFormat === 'text' ? '纯文本保存模式' : outputFormat === 'markdown' ? 'Markdown 保存模式' : '自动保留模式'}</strong><span>{outputFormat === 'json' ? '运行结果必须能解析为对象；可选 Schema 只在本机校验，不会写进 prompt。' : outputFormat === 'auto' ? '不添加格式指令、不生成 answer.*；真实 JSON 对象仍可供条件节点读取 structured.*。' : '格式只影响可选的本地 reply 导出，不会替 Agent 改写回答。'}</span></div>
          {outputFormat === 'json' && <div className="schema-editor-block">
            <div className="field-caption">可选 JSON Schema（本地引用）</div>
            <textarea className="schema-editor" rows={8} value={schemaText} placeholder={'{\n  "type": "object",\n  "properties": {\n    "keywords": { "type": "array" }\n  }\n}'} onChange={(event) => { setSchemaText(event.target.value); setSchemaMessage({ tone: 'idle', text: '' }) }} />
            <div className="schema-actions"><button className="mini-button" onClick={validateSchema}><CircleCheck size={12} />校验</button><button className="mini-button" onClick={applySchema}><Check size={12} />应用</button><button className="mini-button" onClick={() => schemaInputRef.current?.click()}><Upload size={12} />导入</button><button className="mini-button" onClick={exportSchema}><Download size={12} />导出</button><button className="mini-button" onClick={() => { setSchemaText(''); onUpdate({ output_schema: undefined }); setSchemaMessage({ tone: 'ok', text: 'Schema 已清除。' }) }}>清除</button></div>
            <input ref={schemaInputRef} type="file" hidden accept="application/json,application/schema+json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) importSchema(file); event.target.value = '' }} />
            {schemaMessage.tone !== 'idle' && <div className={`schema-message ${schemaMessage.tone}`}>{schemaMessage.text}</div>}
          </div>}
          <div className="status-box"><div><span className={`status-dot ${agent?.available ? 'status-online' : ''}`} />Agent 状态</div><span className={agent?.available ? 'status-ready' : 'status-muted'}>{agent?.available ? `${agent.label} ${agent.version || '可用'}` : agent?.message || '未配置或未发现'}</span><small>凭据、API endpoint 和本地可执行文件请前往全局设置。</small></div>
          <div className="inspector-resource-section">
            <div className="inspector-resource-heading"><div><div className="field-caption">挂载技能（跨 Agent 先预览）</div><span className="resource-count">共 {skills.length} 项 · 已选 {selectedSkillCount}</span></div><button className="mini-button" type="button" aria-expanded={skillExpanded} aria-label={skillExpanded ? '收起技能列表' : '展开技能列表'} onClick={() => setSkillExpanded((expanded) => !expanded)}>{skillExpanded ? '收起' : '展开'}</button></div>
            {skillExpanded && <>
              <input className="resource-search" type="search" aria-label="搜索技能名称" value={skillSearch} onChange={(event) => setSkillSearch(event.target.value)} placeholder="按名称搜索技能" />
              {skills.length === 0 ? <small className="empty-note">尚未导入技能。</small> : visibleSkills.length === 0 ? <small className="resource-empty">没有匹配的技能。</small> : <div className="skill-select-list">{visibleSkills.map((skill) => { const checked = selectedSkillIds.includes(skill.id); const nextIds = checked ? selectedSkillIds.filter((id) => id !== skill.id) : [...selectedSkillIds, skill.id]; return <label key={skill.id} className={`skill-check ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => { onUpdate({ skill_ids: nextIds }); setMountPreview({ tone: 'loading', text: '正在请求 SkillHub mount preview…' }); void onPreviewSkillMount(data.cli || 'codex', nextIds).then((result) => setMountPreview({ tone: result.status === 'error' ? 'error' : 'ok', text: result.status === 'error' ? 'SkillHub 预览返回错误，请检查下方记录。' : (result.skills || []).map((item) => `${item.skill_id || 'skill'}：${item.message || item.status || '已检查'}`).join('；') || 'SkillHub 已返回预览结果；成功预览不代表已执行。' })).catch((error) => setMountPreview({ tone: 'error', text: `SkillHub 挂载预览失败：${error instanceof Error ? error.message : String(error)}` })) }} /><ShieldCheck size={13} />{skill.name}</label> })}</div>}
            </>}
          </div>
          {mountPreview.tone !== 'idle' && <div className={`mount-preview ${mountPreview.tone}`}><span>{mountPreview.tone === 'loading' ? <LoaderCircle size={13} className="spin" /> : mountPreview.tone === 'ok' ? <CircleCheck size={13} /> : <CircleX size={13} />}</span>{mountPreview.text}</div>}
          {kind === 'analyzer' && selectedSkillIds.length > 0 && <div className="dependency-check-card">
            <div className="inspector-resource-heading"><div><div className="field-caption">SKILL DEPENDENCY CHECK</div><span className="resource-count">{dependencyCheck ? `${dependencyCheck.skills.length} 项 · ${dependencyCheck.cache?.hits || 0} 次命中` : autoCheckMounts ? '自动检查已开启' : '自动检查已关闭'}</span></div><div className="dependency-check-actions"><button className="mini-button" type="button" onClick={() => void runDependencyCheck(false)} disabled={dependencyCheckBusy}>{dependencyCheckBusy ? <LoaderCircle size={12} className="spin" /> : <RefreshCw size={12} />}检查</button><button className="mini-button" type="button" onClick={() => void runDependencyCheck(true)} disabled={dependencyCheckBusy}>强制重查</button></div></div>
            <div className="dependency-editor">
              <div className="field-caption">EDIT DECLARED DEPENDENCIES</div>
              <div className="dependency-editor-heading"><span>依赖声明</span><select aria-label="选择要编辑依赖声明的 Skill" value={dependencyEditSkillId} onChange={(event) => setDependencyEditSkillId(event.target.value)}>{selectedSkillIds.map((skillId) => <option key={skillId} value={skillId}>{skills.find((skill) => skill.id === skillId)?.name || skillId}</option>)}</select></div>
              <textarea className="dependency-editor-input" rows={6} value={dependencyEditSkillId ? dependencyDrafts[dependencyEditSkillId] ?? JSON.stringify(dependencyCheck?.skills.find((item) => item.skill_id === dependencyEditSkillId)?.declared_dependencies || {}, null, 2) : '{}'} onChange={(event) => { if (dependencyEditSkillId) setDependencyDrafts((current) => ({ ...current, [dependencyEditSkillId]: event.target.value })); setDependencyEditMessage(null) }} placeholder={'{\n  "tools": ["ffmpeg"],\n  "env": ["OPENAI_API_KEY"],\n  "services": [],\n  "network": true\n}'} />
              <div className="dependency-editor-actions"><small>仅保存 tools / env / services / network 声明；不会执行 Skill、脚本、MCP 或模型。</small><button className="mini-button" type="button" onClick={() => void saveDependencyDeclaration()} disabled={!dependencyEditSkillId || dependencyEditBusy}>{dependencyEditBusy ? <LoaderCircle size={12} className="spin" /> : <Save size={12} />}保存并检查</button></div>
              {dependencyEditMessage && <div className={`schema-message ${dependencyEditMessage.tone}`}>{dependencyEditMessage.text}</div>}
            </div>
            <small className="helper-copy">只做 SkillHub 静态依赖与少量可信版本探针；不会执行 SKILL.md、用户脚本、npm 安装、MCP 服务或模型调用。</small>
            {dependencyCheckError && <div className="schema-message error">检查失败：{dependencyCheckError}</div>}
            {dependencyCheck && <div className="dependency-result-list">{dependencyCheck.skills.map((item: DependencySkillResult) => <div className={`dependency-result-row ${item.blocking ? 'blocked' : item.status === 'manual' ? 'manual' : 'ready'}`} key={item.skill_id}><div className="dependency-result-heading"><span><strong>{item.skill_id}</strong><small>{item.status === 'ready' ? '静态检查通过' : item.status === 'manual' ? '需要人工确认' : item.status === 'runtime_failed' ? 'Agent runtime 失败' : item.status === 'blocked' ? '声明依赖缺失' : item.status}</small></span><span>{item.cache_hit ? '缓存命中' : item.checked_at ? new Date(item.checked_at).toLocaleString() : '刚检查'}</span></div><small>{item.message || '未提供说明'}{item.runtime?.interpreter ? ` · ${item.runtime.interpreter}` : ''}{item.runtime?.version ? ` · ${item.runtime.version}` : ''}</small>{((item.missing || []).length > 0 || (item.needs_manual || []).length > 0) && <details><summary>查看缺项与待确认项</summary><div className="dependency-detail-list">{(item.missing || []).map((missing, index) => <span key={`missing-${index}`} className="dependency-detail missing">缺失：{missing.kind || '依赖'} / {missing.name || '未命名'}</span>)}{(item.needs_manual || []).map((manual, index) => <span key={`manual-${index}`} className="dependency-detail manual">待确认：{manual.kind || '依赖'} / {manual.name || '未命名'}{manual.certainty === 'inferred' ? ' · inferred' : ''}</span>)}</div></details>}</div>)}</div>}
          </div>}
          <div className="inspector-resource-section">
            <div className="inspector-resource-heading"><div><div className="field-caption">挂载 MCP（默认不启用）</div><span className="resource-count">共 {mcps.length} 项 · 已选 {selectedMcpCount}</span></div><button className="mini-button" type="button" aria-expanded={mcpExpanded} aria-label={mcpExpanded ? '收起 MCP 列表' : '展开 MCP 列表'} onClick={() => setMcpExpanded((expanded) => !expanded)}>{mcpExpanded ? '收起' : '展开'}</button></div>
            {mcpExpanded && <>
              <input className="resource-search" type="search" aria-label="搜索 MCP 名称" value={mcpSearch} onChange={(event) => setMcpSearch(event.target.value)} placeholder="按名称搜索 MCP" />
              {mcps.length === 0 ? <small className="empty-note">全局设置中没有已导入 MCP；不会自动扫描或启动服务。</small> : visibleMcps.length === 0 ? <small className="resource-empty">没有匹配的 MCP。</small> : <div className="skill-select-list mcp-select-list">{visibleMcps.map((mcp) => { const checked = selectedMcpIds.includes(mcp.id); const unsupported = mcp.supported === false; return <label key={mcp.id} className={`skill-check ${checked ? 'selected' : ''} ${unsupported ? 'unsupported' : ''}`} title={mcp.reason || ''}><input type="checkbox" disabled={unsupported} checked={checked} onChange={(event) => onUpdate({ mcp_ids: event.target.checked ? [...new Set([...selectedMcpIds, mcp.id])] : selectedMcpIds.filter((id) => id !== mcp.id) })} /><Server size={13} />{mcp.name}<small>{unsupported ? `不支持：${mcp.reason || '目标 Agent 不支持'}` : mcp.transport || '已导入'}</small></label> })}</div>}
            </>}
          </div>
        </>}
        {kind === 'condition' && <>
          <Field label="字段路径" hint="可手填，也可从下方运行样本字段列表选择"><input list={'condition-fields-' + node.id} value={data.field || ''} placeholder="如 structured.route" onChange={(event) => onUpdate({ field: event.target.value })} /><datalist id={'condition-fields-' + node.id}>{(conditionSample?.fields || []).map((field) => <option key={field} value={field} />)}</datalist></Field>
          <Field label="比较方式"><select value={data.operator || 'equals'} onChange={(event) => onUpdate({ operator: event.target.value })}><option value="equals">等于</option><option value="contains">包含</option><option value="exists">存在</option><option value="gt">大于</option><option value="gte">大于等于</option><option value="lt">小于</option><option value="lte">小于等于</option></select></Field>
          <Field label="预期值"><input value={data.expected || ''} onChange={(event) => onUpdate({ expected: event.target.value })} /></Field>
          <Field label="字段缺失时"><select value={data.missing_strategy || 'error'} onChange={(event) => onUpdate({ missing_strategy: event.target.value as KxyNodeData['missing_strategy'] })}><option value="error">报错并停止</option><option value="false">按假分支</option><option value="true">按真分支</option></select></Field>
          <div className="condition-preview"><span>样本来源</span><span>{conditionSample?.source || '暂无运行样本'}</span><span>当前值</span><code>{conditionSample ? JSON.stringify(conditionSample.value) : '（运行后显示；字段仍可手填）'}</code></div>
        </>}
        {kind === 'filter' && <>
          <p className="helper-copy">过滤器只筛选“允许传给下游”的附件，不删除、移动或改写原文件和上游结果。被排除项只展示安全元数据。</p>
          <Field label="名称规则"><input value={data.name_pattern || '*'} maxLength={512} onChange={(event) => onUpdate({ name_pattern: event.target.value })} /></Field>
          <div className="two-fields"><Field label="规则类型"><select value={data.pattern_mode || 'glob'} onChange={(event) => onUpdate({ pattern_mode: event.target.value as KxyNodeData['pattern_mode'] })}><option value="glob">glob（默认）</option><option value="regex">regex（有界超时）</option></select></Field><Field label="匹配范围"><select value={data.name_scope || 'basename'} onChange={(event) => onUpdate({ name_scope: event.target.value as KxyNodeData['name_scope'] })}><option value="basename">文件名</option><option value="relative_path">文件夹相对路径</option></select></Field></div>
          <div className="field-caption">格式（与名称规则 AND）</div><div className="format-check-list generated-file-list">{['*', '.pdf', '.md', '.txt', '.csv', '.xlsx', '.html', '.yaml', '.yml', '.json', '.png', '.jpg'].map((extension) => { const selected = (data.extensions || ['*']).includes(extension); return <label className={'check-field compact-check ' + (selected ? 'selected' : '')} key={extension}><input type="checkbox" checked={selected} onChange={(event) => { const current = data.extensions || ['*']; const next = extension === '*' ? (event.target.checked ? ['*'] : current.filter((item) => item !== '*')) : (event.target.checked ? [...new Set([...current.filter((item) => item !== '*'), extension])] : current.filter((item) => item !== extension)); onUpdate({ extensions: next }) }} /><span>{extension}</span></label> })}</div>
          <Field label="自定义扩展名" hint="逗号分隔；支持 pdf、.pdf、*.pdf；填写后会关闭 * 通配"><input value={data.custom_extensions || ''} onChange={(event) => { const value = event.target.value; onUpdate({ custom_extensions: value, ...(value.trim() ? { extensions: (data.extensions || []).filter((item) => item !== '*') } : {}) }) }} placeholder="例如 docx,*.pptx" /></Field>
          <Field label="regex 超时（毫秒）" hint="每次预览/运行整批匹配共享有界时间"><input type="number" min={1} max={1000} value={data.timeout_ms || 100} onChange={(event) => onUpdate({ timeout_ms: Number(event.target.value) })} /></Field>
          <button className="outline-button full-width" type="button" onClick={() => { setFilterPreview({ tone: 'loading', text: '正在按运行时相同规则预览…' }); void api<{ matched_count?: number; excluded_count?: number; matched?: Array<Record<string, unknown>>; excluded?: Array<Record<string, unknown>> }>('/api/filters/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: data, items: filterItems || [] }) }).then((result) => { const names = (items: Array<Record<string, unknown>> | undefined) => (items || []).map((item) => String(item.name || item.relative_path || '')).filter(Boolean).join('、'); setFilterPreview({ tone: 'ok', text: '匹配 ' + (result.matched_count || 0) + ' 项' + (names(result.matched) ? '：' + names(result.matched) : '') + '；排除 ' + (result.excluded_count || 0) + ' 项' + (names(result.excluded) ? '：' + names(result.excluded) : '') }) }).catch((error) => setFilterPreview({ tone: 'error', text: error instanceof Error ? error.message : '过滤预览失败' })) }}><Filter size={13} />预览当前上游附件</button>
          {filterPreview.tone !== 'idle' && <div className={'schema-message ' + filterPreview.tone}>{filterPreview.text}</div>}
        </>}
        {kind === 'container' && <>
          <p className="helper-copy">输出容器只收集活动分支的结果，并写入每次运行独立目录。授权文件夹需要你明确选择。</p>
          <div className="container-reply-card"><div className="reply-preview-heading"><div><span className="field-caption">READABLE REPLY</span><strong>正文回复</strong></div><span>{containerReplyLabel}</span></div><textarea rows={8} readOnly value={containerReplyText} placeholder={containerReplyPlaceholder} />{containerAttribution && <small>上游归因：{containerAttribution}</small>}<small>这里是当前输出容器的只读运行快照；编辑副本、JSON 校验与下载在下方执行面板中完成。</small></div>
          <div className="field-caption">正文回复导出（可选）</div>
          <div className="selection-scope-row"><span>范围：当前正文副本格式（3 项）</span><button className="mini-button" type="button" onClick={() => updateReplyFormats('all')}>全选正文</button><button className="mini-button" type="button" onClick={() => updateReplyFormats('invert')}>反选正文</button></div>
          <div className="format-check-list">{(['markdown', 'text', 'json'] as ReplyExportFormat[]).map((format) => { const checked = containerFormats.includes(format); const label = format === 'markdown' ? 'Markdown（.md）' : format === 'text' ? '纯文本（.txt）' : 'JSON（.json）'; const title = format === 'markdown' ? '生成可读的 result.md 正文副本。' : format === 'text' ? '生成不带 Markdown 约定的 result.txt 正文副本。' : '生成 result.json；内容模式只保留正文/结构化 content。'; return <label key={format} title={title} className={`check-field compact-check ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={(event) => { const next = event.target.checked ? [...containerFormats, format] : containerFormats.filter((item) => item !== format); onUpdate({ export_formats: next }) }} /><span>{label}</span></label> })}</div>
          <div className="output-policy-card"><div className="settings-card-heading"><div><span className="field-caption">GENERATED FILES</span><strong>接收文件扩展名</strong></div><span className="settings-count">{hasFileAllowlist ? (allowedFileExtensions.length ? `${allowedFileExtensions.length} 项` : '不接收') : '兼容旧流程'}</span></div><p className="helper-copy">只复制真实生成且位于 outputs/ 内的文件；不会把正文转换成文件。空数组表示文件留在运行目录，不进入授权输出。</p><div className="selection-scope-row"><span>范围：当前生成文件扩展名（{GENERATED_FILE_EXTENSIONS.length} 项）</span><button className="mini-button" type="button" onClick={() => updateGeneratedFileExtensions('all')}>全选文件</button><button className="mini-button" type="button" onClick={() => updateGeneratedFileExtensions('invert')}>反选文件</button></div><div className="format-check-list generated-file-list">{GENERATED_FILE_EXTENSIONS.map((extension) => { const checked = allowedFileExtensions.includes(extension); return <label key={extension} title={`允许容器接收原始 ${extension} 文件；不会把正文转换成 ${extension}。`} className={`check-field compact-check ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={(event) => { const next = event.target.checked ? [...allowedFileExtensions, extension] : allowedFileExtensions.filter((item) => item !== extension); onUpdate({ allowed_file_extensions: next }) }} /><span>{extension}</span></label> })}</div></div>
          <Field label="JSON 文件内容" hint="完整模式保留容器元数据；内容模式只导出正文/结构化 content">
            <select value={data.json_mode || 'full'} disabled={!containerFormats.includes('json')} onChange={(event) => onUpdate({ json_mode: event.target.value as 'content' | 'full' })}><option value="full" title="保留 status、items、content、正文和溯源元数据。">完整记录</option><option value="content" title="只导出最终内容；单个 JSON 对象保持对象类型，多输入保持数组。">仅内容</option></select>
          </Field>
          <Field label="输出文件夹授权"><select value={data.grant_id || ''} onChange={(event) => onUpdate({ grant_id: event.target.value })}><option value="">仅保存在运行目录</option>{grants.filter((grant) => !grant.revoked_at).map((grant) => <option key={grant.id} value={grant.id}>{grant.canonical_path}</option>)}</select></Field>
          <button className="outline-button full-width" onClick={onAuthorize}><HardDrive size={14} />授权一个输出文件夹</button>
          <div className="grant-list">{grants.map((grant) => <div className={grant.revoked_at ? 'grant-row revoked' : 'grant-row'} key={grant.id}><span>{grant.canonical_path}</span>{!grant.revoked_at && <button className="mini-button" onClick={() => onRevoke(grant.id)}>撤销</button>}</div>)}</div>
        </>}
        {kind === 'human' && <>
          <Field label="确认说明" hint="支持纯文本或 Markdown；运行时会安全转义预览"><textarea rows={9} value={String(data.content || '')} onChange={(event) => onUpdate({ content: event.target.value })} /></Field>
          <Field label="确认按钮文字"><input value={data.confirm_label || '确认继续'} onChange={(event) => onUpdate({ confirm_label: event.target.value })} /></Field>
          <label className="check-field loop-toggle"><input type="checkbox" checked={data.review_gate === true} onChange={(event) => onUpdate({ review_gate: event.target.checked })} /><span>循环审阅闸门</span><small>只有 reviewer → 此人工节点 → subflow_output 的内部拓扑支持“退回修改”；其他位置只能通过或终止。</small></label>
          <div className="status-box"><div><span className="status-dot" />运行行为</div><span className="status-muted">到达此节点后等待人工决定，不会因刷新或超时自动通过。</span></div>
        </>}
        {kind === 'blackbox' && <>
          <p className="helper-copy">黑盒子是真实可执行的嵌套工作流，不是装饰分组。内部必须保留一个 items 输入标记和一个 result 输出标记。</p>
          <div className="blackbox-summary"><span>内部节点</span><strong>{data.workflow?.nodes?.filter((item) => !['subflow_input', 'subflow_output'].includes(String(item.type))).length || 0}</strong><span>内部边</span><strong>{data.workflow?.edges?.length || 0}</strong></div>
          <div className={`loop-config-card ${loopConfig.enabled ? 'enabled' : ''}`}>
            <label className="check-field loop-toggle"><input type="checkbox" checked={loopConfig.enabled} onChange={(event) => updateLoop({ enabled: event.target.checked })} /><span>启用有界循环</span><small>外层仍是一个黑盒节点；每轮重新运行内部 DAG。</small></label>
            {loopConfig.enabled && <>
              <div className="loop-config-title"><span className="field-caption">LOOP CONTROL</span><span>审阅器必须返回严格 JSON</span></div>
              {innerAnalyzers.length < 2 && <div className="schema-message error">至少需要两个内部分析器，分别作为执行器和审阅器。</div>}
              <div className="two-fields"><Field label="执行器"><select value={loopConfig.executor_id} onChange={(event) => updateLoop({ executor_id: event.target.value })}>{innerAnalyzers.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.data.label}</option>)}</select></Field><Field label="审阅器"><select value={loopConfig.reviewer_id} onChange={(event) => updateLoop({ reviewer_id: event.target.value })}>{innerAnalyzers.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.data.label}</option>)}</select></Field></div>
              <Field label="原始目标" hint="为空时使用循环输入摘要"><input value={loopConfig.goal} onChange={(event) => updateLoop({ goal: event.target.value })} placeholder="例如：把结果整理到可核查结论" /></Field>
              <Field label="输入字段" hint="从单个上游对象提取本轮 selected_input"><input value={loopConfig.input_field} onChange={(event) => updateLoop({ input_field: event.target.value })} /></Field>
              <div className="two-fields"><Field label="最大轮数"><input type="number" min={1} max={50} value={loopConfig.max_rounds} onChange={(event) => updateLoop({ max_rounds: Number(event.target.value) })} /></Field><Field label="活动预算（秒）"><input type="number" min={1} max={86400} value={loopConfig.active_budget_seconds} onChange={(event) => updateLoop({ active_budget_seconds: Number(event.target.value) })} /></Field></div>
              <Field label="历史摘要字符数" hint="只把摘要带入下一轮；人工等待不消耗活动预算"><input type="number" min={0} max={20000} value={loopConfig.previous_summary_chars} onChange={(event) => updateLoop({ previous_summary_chars: Number(event.target.value) })} /></Field>
              <div className="field-caption">下一轮可见反馈</div>
              <div className="loop-feedback-list">{([['latest_result', '最新执行器结果'], ['issues', '审阅问题'], ['next_action', '下一步动作'], ['history_summary', '历史摘要']] as Array<[keyof LoopFeedback, string]>).map(([key, label]) => <label className="check-field compact-check" key={key}><input type="checkbox" checked={loopConfig.feedback[key]} onChange={(event) => updateLoop({ feedback: { [key]: event.target.checked } })} /><span>{label}</span></label>)}</div>
              <div className="field-caption">审阅 JSON 字段映射</div>
              <div className="two-fields loop-review-fields"><Field label="passed"><input value={loopConfig.review_fields.passed} onChange={(event) => updateLoop({ review_fields: { passed: event.target.value } })} /></Field><Field label="issues"><input value={loopConfig.review_fields.issues} onChange={(event) => updateLoop({ review_fields: { issues: event.target.value } })} /></Field></div>
              <Field label="next_action"><input value={loopConfig.review_fields.next_action} onChange={(event) => updateLoop({ review_fields: { next_action: event.target.value } })} /></Field>
              <div className="status-box loop-prompt-note"><div><span className="status-dot" />Prompt 来源</div><span className="status-muted">审阅器 prompt 保存在上方选中的内部分析器中，进入内部画布可直接编辑；循环配置不另存一份 prompt。</span></div>
            </>}
          </div>
          <button className="run-button full-width" onClick={onEnterBlackbox}><CornerDownLeft size={14} />进入编辑内部画布</button>
          <button className="outline-button full-width" onClick={onUnpackBlackbox}><PackageOpen size={14} />解包并保留连线</button>
        </>}
        {(kind === 'subflow_input' || kind === 'subflow_output') && <div className="status-box"><div><span className="status-dot" />黑盒边界标记</div><span className="status-muted">{kind === 'subflow_input' ? '外部输入会从 items 进入内部图。' : '内部结果会从 result 返回外部图。'}</span></div>}
        {!['subflow_input', 'subflow_output'].includes(kind) && <button className="outline-button full-width" onClick={onSavePreset}><Save size={14} />保存为{nodeTypeLabel}预设</button>}
      </div>
    </aside>
  )
}

function approvalStatusLabel(status: string): string {
  if (status === 'pending' || status === 'waiting') return '待人工确认'
  if (status === 'approved') return '已通过'
  if (status === 'returned') return '已退回下一轮'
  if (status === 'rejected') return '已拒绝'
  if (status === 'cancelled') return '已取消'
  return status
}

function attemptStatusLabel(status: string): string {
  if (status === 'queued' || status === 'pending') return '排队中'
  if (status === 'running') return '运行中'
  if (status === 'waiting') return '等待人工确认'
  if (status === 'succeeded') return '已完成'
  if (status === 'failed') return '执行失败'
  if (status === 'rejected') return '人工拒绝'
  if (status === 'cancelled') return '已取消'
  if (status === 'interrupted') return '服务重启中断'
  return status
}

function approvalFileRefs(value: unknown): Array<{ path: string; name: string }> {
  const found = new Map<string, { path: string; name: string }>()
  const visit = (candidate: unknown) => {
    if (Array.isArray(candidate)) {
      candidate.forEach(visit)
      return
    }
    if (!candidate || typeof candidate !== 'object') return
    const item = candidate as Record<string, unknown>
    if (typeof item.file_path === 'string' && item.file_path.trim()) {
      const path = item.file_path.replaceAll('\\', '/')
      found.set(path, { path, name: String(item.display_name || item.name || path.split('/').pop() || path) })
    }
    if (Array.isArray(item.artifacts)) item.artifacts.forEach((artifact) => {
      if (!artifact || typeof artifact !== 'object') return
      const record = artifact as Record<string, unknown>
      if (typeof record.path === 'string' && record.path.trim()) {
        const path = record.path.replaceAll('\\', '/')
        found.set(path, { path, name: String(record.name || path.split('/').pop() || path) })
      }
    })
    ;['items', 'upstream', 'inputs', 'attachments'].forEach((key) => visit(item[key]))
  }
  visit(value)
  return [...found.values()]
}

function approvalText(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return [...new Set(value.map(approvalText).filter(Boolean))].join('\n\n')
  if (!value || typeof value !== 'object') return ''
  const item = value as Record<string, unknown>
  const parts: string[] = []
  if (typeof item.text === 'string' && item.text) parts.push(item.text)
  else if (typeof item.content === 'string' && item.content) parts.push(item.content)
  else if (item.content !== undefined) {
    const content = approvalText(item.content)
    if (content) parts.push(content)
  }
  ;['items', 'upstream', 'inputs'].forEach((key) => {
    const nested = approvalText(item[key])
    if (nested && !parts.includes(nested)) parts.push(nested)
  })
  return parts.join('\n\n')
}

function approvalRevisionText(value: unknown): string {
  if (!Array.isArray(value)) return approvalText(value)
  const executor = value.find((item) => item && typeof item === 'object' && (item as Record<string, unknown>).role === 'executor')
  return executor ? approvalText(executor) : approvalText(value)
}

function ApprovalCard({ runId, approval, onDecision }: { runId: string; approval: NonNullable<Run['approvals']>[number]; onDecision: (nodeId: string, decision: 'approve' | 'reject' | 'return', note: string, revisionText?: string | null) => void }) {
  const [note, setNote] = useState('')
  const [editingRevision, setEditingRevision] = useState(false)
  const [revisionText, setRevisionText] = useState(approval.revision_text ?? approvalRevisionText(approval.inputs))
  const waiting = approval.status === 'pending' || approval.status === 'waiting'
  useEffect(() => {
    setRevisionText(approval.revision_text ?? approvalRevisionText(approval.inputs))
    setEditingRevision(false)
  }, [approval.node_id, approval.status, approval.revision_text])
  const files = approvalFileRefs(approval.inputs)
  const readableInput = approvalText(approval.inputs)
  const revisionValue = editingRevision ? revisionText : undefined
  return <article className={'approval-card approval-' + approval.status}><div className="approval-heading"><div><span className="field-caption">人工节点</span><strong title={approval.node_id}>{approval.node_id}</strong></div><span className="approval-status">{approvalStatusLabel(approval.status)}</span></div>{approval.content && <div className="approval-readable-body"><div className="field-caption">可读审阅内容</div><p className="approval-content">{approval.content}</p></div>}{readableInput && <div className="approval-readable-body approval-upstream-body"><div className="field-caption">上游正文 / 结果</div><pre className="approval-content">{readableInput}</pre></div>}{files.length > 0 && <div className="approval-file-links"><div className="field-caption">已验证附件（仅当前审批输入白名单）</div>{files.map((file) => <a key={file.path} className="artifact-link" href={API + '/api/runs/' + encodeURIComponent(runId) + '/approval-file/' + encodeURIComponent(approval.node_id) + '?path=' + encodeURIComponent(file.path)} target="_blank" rel="noreferrer"><Download size={12} />{file.name}</a>)}</div>}{approval.inputs !== undefined && <details className="approval-raw"><summary>展开原始结构数据（只读）</summary><pre className="approval-inputs">{JSON.stringify(approval.inputs, null, 2).slice(0, 12000)}</pre></details>}{approval.decision && <p className="approval-decision">决定：{approval.decision}{approval.note ? ' · ' + approval.note : ''}{approval.revision_text !== null && approval.revision_text !== undefined ? ' · 已保存修订副本' : ''}</p>}{waiting && <><label className="check-field compact-check"><input type="checkbox" checked={editingRevision} onChange={(event) => setEditingRevision(event.target.checked)} /><span>编辑修订副本</span><small>原始输入保留在运行记录；修订只影响后续节点。</small></label>{editingRevision && <textarea className="approval-revision" rows={8} value={revisionText} onChange={(event) => setRevisionText(event.target.value)} placeholder="输入要传给后续节点的修订正文；清空也会保存为明确修订。" /> }<textarea className="approval-note" rows={2} value={note} placeholder="备注 / 退回反馈（会进入运行记录）" onChange={(event) => setNote(event.target.value)} /><div className="approval-actions"><button className="outline-button" onClick={() => onDecision(approval.node_id, 'reject', note, revisionValue)}>终止并停止</button>{approval.allow_return && <button className="outline-button" onClick={() => onDecision(approval.node_id, 'return', note, revisionValue)} disabled={!note.trim() && !editingRevision}>退回下一轮</button>}<button className="run-button" onClick={() => onDecision(approval.node_id, 'approve', note, revisionValue)}><Check size={13} />{approval.confirm_label || '通过并继续'}</button></div></>}</article>
}

function loopRoundStatusLabel(status: string): string {
  if (status === 'running') return '执行中'
  if (status === 'reviewed') return '审阅未通过，准备下一轮'
  if (status === 'succeeded') return '审阅通过'
  if (status === 'budget_waiting') return '活动预算已暂停'
  if (status === 'round_limit_waiting') return '轮数上限已暂停'
  if (status === 'reused') return '检查点复用'
  if (status === 'failed') return '本轮失败'
  if (status === 'interrupted') return '服务重启中断'
  return status
}

function loopValueText(value: unknown, limit = 8000): string {
  if (typeof value === 'string') return value.slice(0, limit)
  if (value === undefined || value === null) return '（空）'
  try {
    return JSON.stringify(value, null, 2).slice(0, limit)
  } catch {
    return String(value).slice(0, limit)
  }
}

function loopDiffText(previous: unknown, current: unknown): string {
  const before = loopValueText(previous).split('\n')
  const after = loopValueText(current).split('\n')
  if (before.join('\n') === after.join('\n')) return '（本轮没有可见文本变化）'
  return [...before.map((line) => `− ${line}`), ...after.map((line) => `＋ ${line}`)].join('\n').slice(0, 12000)
}

function RunPanel({ run, history, open, onToggle, onCancel, onResume, onClear, onOpenHistory, onApproval, onLoopContinue, onLoopStop }: { run: Run | null; history: RunSummary[]; open: boolean; onToggle: () => void; onCancel: () => void; onResume: () => void; onClear: () => void; onOpenHistory: (id: string) => void; onApproval: (nodeId: string, decision: 'approve' | 'reject' | 'return', note: string, revisionText?: string | null) => void; onLoopContinue: (loopPath: string, additionalRounds?: number, additionalSeconds?: number) => void; onLoopStop: (loopPath: string) => void }) {
  const [jsonDraft, setJsonDraft] = useState('')
  const [textDraft, setTextDraft] = useState('')
  const [editingCopy, setEditingCopy] = useState(false)
  const [copyMessage, setCopyMessage] = useState<{ tone: 'idle' | 'ok' | 'error'; text: string }>({ tone: 'idle', text: '' })
  const jsonInputRef = useRef<HTMLInputElement>(null)
  const outputs = run?.output_manifest?.outputs
  const outputEntries = outputs ? Object.entries(outputs) : []
  const defaultOutputKey = outputEntries.slice().reverse().find(([, value]) => value && typeof value === 'object' && !Array.isArray(value) && ('export_formats' in value || 'artifact_count' in value))?.[0] || outputEntries[outputEntries.length - 1]?.[0] || ''
  const [selectedOutputKey, setSelectedOutputKey] = useState('')
  const [selectedLoopKey, setSelectedLoopKey] = useState('')
  const loopRounds = run?.loop_rounds || []
  const latestLoopRound = loopRounds[loopRounds.length - 1]
  const selectedLoopRound = loopRounds.find((item) => `${item.loop_path}:${item.attempt_no}:${item.round_no}` === selectedLoopKey) || latestLoopRound
  const waitingLoopRound = loopRounds.slice().reverse().find((item) => ['budget_waiting', 'round_limit_waiting'].includes(item.status))
  const selectedOutput = outputEntries.find(([key]) => key === selectedOutputKey)?.[1] ?? outputEntries.find(([key]) => key === defaultOutputKey)?.[1]
  const outputSnapshot = outputs ? JSON.stringify(outputs, null, 2) : ''
  const selectedOutputRecord = selectedOutput && typeof selectedOutput === 'object' && !Array.isArray(selectedOutput) ? selectedOutput as Record<string, unknown> : null
  const selectedOutputForCopy = selectedOutputRecord?.json_mode === 'content' && 'content' in selectedOutputRecord ? selectedOutputRecord.content : selectedOutput
  const selectedOutputSnapshot = selectedOutputForCopy === undefined ? '' : JSON.stringify(selectedOutputForCopy, null, 2)
  const textFromValue = (value: unknown): string => {
    if (typeof value === 'string') return value
    if (Array.isArray(value)) return value.map(textFromValue).filter(Boolean).join('\n\n')
    if (!value || typeof value !== 'object') return ''
    const item = value as Record<string, unknown>
    if (typeof item.text === 'string') return item.text
    if (typeof item.content === 'string') return item.content
    if (item.content !== undefined) return textFromValue(item.content)
    if (item.items !== undefined) return textFromValue(item.items)
    return ''
  }
  useEffect(() => {
    setSelectedOutputKey((current) => outputEntries.some(([key]) => key === current) ? current : defaultOutputKey)
  }, [run?.id, outputSnapshot, defaultOutputKey])
  useEffect(() => {
    const latestKey = latestLoopRound ? `${latestLoopRound.loop_path}:${latestLoopRound.attempt_no}:${latestLoopRound.round_no}` : ''
    setSelectedLoopKey((current) => loopRounds.some((item) => `${item.loop_path}:${item.attempt_no}:${item.round_no}` === current) ? current : latestKey)
  }, [run?.id, loopRounds.length, latestLoopRound?.loop_path, latestLoopRound?.attempt_no, latestLoopRound?.round_no])
  useEffect(() => {
    setJsonDraft(selectedOutputSnapshot)
    setTextDraft(textFromValue(selectedOutput))
    setEditingCopy(false)
    setCopyMessage({ tone: 'idle', text: '' })
  }, [run?.id, selectedOutputKey, selectedOutputSnapshot])
  if (!open) return <button className="run-dock" onClick={onToggle}><span className="run-dock-dot" />{run ? `运行 ${run.status}` : '执行记录'}<ChevronDown size={15} /></button>
  const statusText = run?.status === 'succeeded' ? '已完成' : run?.status === 'failed' ? '执行失败' : run?.status === 'cancelled' ? '已取消' : run?.status === 'rejected' ? '人工拒绝' : run?.status === 'interrupted' ? '服务重启中断' : run?.status === 'waiting' && waitingLoopRound ? '循环暂停，等待有界继续' : run?.status === 'waiting' ? '等待人工确认' : '运行中'
  const validateCopy = () => {
    try {
      const parsed = JSON.parse(jsonDraft) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('JSON 副本必须是对象')
      setCopyMessage({ tone: 'ok', text: 'JSON 副本有效；运行记录与原始产物未被修改。' })
    } catch (error) {
      setCopyMessage({ tone: 'error', text: error instanceof Error ? error.message : 'JSON 副本无效' })
    }
  }
  const importCopy = (file: File) => {
    void file.text().then((content) => {
      const parsed = JSON.parse(content) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('导入内容必须是 JSON 对象')
      setJsonDraft(JSON.stringify(parsed, null, 2))
      setTextDraft(textFromValue(parsed))
      setEditingCopy(true)
      setCopyMessage({ tone: 'ok', text: 'JSON 已导入为本地副本；点击下载或继续编辑即可。' })
    }).catch((error) => setCopyMessage({ tone: 'error', text: error instanceof Error ? error.message : 'JSON 文件无法读取' }))
  }
  const downloadCopy = (content: string, filename: string, type: string) => {
    let normalizedContent = content
    if (filename.endsWith('.json')) {
      if (!content.trim()) {
        normalizedContent = '{}'
        setCopyMessage({ tone: 'ok', text: '正文为空，已下载空 JSON 副本；运行记录与原始产物未被修改。' })
      }
      try {
        const parsed = JSON.parse(normalizedContent) as unknown
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('JSON 副本必须是对象')
        normalizedContent = JSON.stringify(parsed, null, 2)
        if (content.trim()) setCopyMessage({ tone: 'ok', text: 'JSON 已校验并下载为本地副本；运行记录与原始产物未被修改。' })
      } catch (error) {
        setCopyMessage({ tone: 'error', text: error instanceof Error ? error.message : 'JSON 副本无效，未下载文件' })
        return
      }
    }
    const url = URL.createObjectURL(new Blob([normalizedContent], { type })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url)
  }
  const outputArtifacts = (value: unknown): Array<Record<string, unknown>> => Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item))) : []
  const acceptedArtifacts = selectedOutputRecord ? outputArtifacts(selectedOutputRecord.artifacts) : []
  const excludedArtifacts = selectedOutputRecord ? outputArtifacts(selectedOutputRecord.excluded_artifacts) : []
  const attribution = selectedOutputRecord ? collectTransportAttribution(selectedOutputRecord) : ''
  const visibleReply = editingCopy ? textDraft : textFromValue(selectedOutput)
  const hasActualArtifacts = acceptedArtifacts.length > 0 || excludedArtifacts.length > 0 || Boolean(run?.output_manifest?.artifacts?.length)
  const replyLabel = visibleReply.trim() ? '可复制 / 可下载' : hasActualArtifacts ? '本次仅生成文件' : '尚无正文回复'
  const replyPlaceholder = hasActualArtifacts ? '（无正文回复；本次运行仅生成文件）' : '（尚无正文回复）'
  return (
    <section className="run-panel">
      <div className="run-header"><div><span className="eyebrow">EXECUTION</span><h3>{run ? `运行 ${run.id.slice(0, 8)}` : '尚未执行'}</h3></div><div className="run-actions">{run && ['pending', 'running', 'waiting'].includes(run.status) && <button className="danger-button" onClick={onCancel}><Square size={13} />取消</button>}{run && ['failed', 'interrupted'].includes(run.status) && <button className="run-button resume-button" onClick={onResume} title="使用原始运行快照和已验证 checkpoint 重试失败或中断节点"><RefreshCw size={13} />从检查点恢复</button>}{run && <button className="icon-button" onClick={onClear} title="清除面板"><X size={15} /></button>}<button className="icon-button" onClick={onToggle} title="收起执行面板"><ChevronDown size={16} /></button></div></div>
      {run ? <div className="run-body">
        <div className={`run-status status-${run.status}`}><span className="status-dot" />{statusText}{run.error && <span className="run-error">{run.error}</span>}</div>
        {loopRounds.length > 0 && selectedLoopRound && <div className="loop-details">
          <div className="loop-details-heading"><div><span className="field-caption">LOOP ROUNDS</span><strong>{selectedLoopRound.loop_path}</strong></div><span className={`loop-round-status loop-${selectedLoopRound.status}`}>{loopRoundStatusLabel(selectedLoopRound.status)}</span></div>
          <div className="loop-round-toolbar"><label>轮次<select aria-label="选择循环轮次" value={selectedLoopKey} onChange={(event) => setSelectedLoopKey(event.target.value)}>{loopRounds.map((item) => <option key={`${item.loop_path}:${item.attempt_no}:${item.round_no}`} value={`${item.loop_path}:${item.attempt_no}:${item.round_no}`}>{item.loop_path} · 尝试 {item.attempt_no} · 第 {item.round_no} 轮 · {loopRoundStatusLabel(item.status)}</option>)}</select></label><span>{Math.round(selectedLoopRound.active_seconds || 0)} / {Math.round(selectedLoopRound.budget_seconds || 0)} 秒 · 上限 {selectedLoopRound.effective_max_rounds || '—'} 轮</span></div>
          {waitingLoopRound && <div className="loop-control-bar"><span>{waitingLoopRound.loop_path} 正在等待人工控制，继续会增加有界预算。</span><button className="run-button" onClick={() => onLoopContinue(waitingLoopRound.loop_path, 1, 300)}><RefreshCw size={12} />增加 1 轮 / 5 分钟</button><button className="danger-button" onClick={() => onLoopStop(waitingLoopRound.loop_path)}><Square size={12} />停止且不接受</button></div>}
          <div className="loop-round-grid"><div><span className="field-caption">本轮输入 / 可见上下文</span><pre>{loopValueText(selectedLoopRound.executor_input || selectedLoopRound.original_input, 5200)}</pre></div><div><span className="field-caption">执行器结果</span><pre>{loopValueText(selectedLoopRound.executor_output, 5200)}</pre></div><div><span className="field-caption">审阅结果</span><pre>{loopValueText(selectedLoopRound.reviewer_output, 3200)}</pre></div></div>
          <details className="loop-diff"><summary>上下文与执行器结果变化预览</summary><pre>{loopDiffText(selectedLoopRound.previous_summary, selectedLoopRound.executor_output)}</pre></details>
        </div>}
        {(run.attempts || []).length > 0 && <div className="attempt-history"><div className="field-caption">恢复审计</div>{(run.attempts || []).map((attempt) => <div className="attempt-row" key={attempt.attempt_no}><span>尝试 {attempt.attempt_no}</span><strong>{attemptStatusLabel(attempt.status)}</strong><small>复用 {attempt.reused_nodes?.length || 0} · 重跑 {attempt.rerun_nodes?.length || 0}</small>{attempt.error && <em title={attempt.error}>{attempt.error}</em>}</div>)}</div>}
        {(run.approvals || []).length > 0 && <div className="approval-list">{(run.approvals || []).map((approval) => <ApprovalCard key={approval.node_id} runId={run.id} approval={approval} onDecision={onApproval} />)}</div>}
        <div className="run-nodes">{(run.nodes || []).map((node) => <div key={node.node_id} className="run-node-row" title={node.node_id}><span className={`node-status-dot ${node.status}`} /><code>{node.node_id}</code><span>{node.status}</span>{node.message && <small>{node.message}</small>}</div>)}</div>
        {outputs && <div className="output-preview">
          <div className="output-heading"><div><span className="field-caption">运行输出</span><select className="output-selector" aria-label="选择要预览的输出节点" value={selectedOutputKey || defaultOutputKey} onChange={(event) => { setSelectedOutputKey(event.target.value); setEditingCopy(false) }}>{outputEntries.map(([key, value]) => <option key={key} value={key}>{key}{value && typeof value === 'object' && !Array.isArray(value) && ('export_formats' in value || 'artifact_count' in value) ? ' · 最终容器' : ''}</option>)}</select></div><span className="output-badge"><Check size={12} />来自运行记录</span></div>
          <div className="reply-preview"><div className="reply-preview-heading"><div><span className="field-caption">READABLE REPLY</span><strong>正文回复</strong></div><span>{replyLabel}</span></div><pre>{visibleReply || replyPlaceholder}</pre>{attribution && <small>上游归因：{attribution}</small>}</div>
          <p className="helper-copy">正文与 JSON 可编辑、导入和下载；这些操作只生成副本，不会改写已完成运行或原始输入。自动模式保留 Agent 原文；空正文也是有效的文件型运行。</p>
          <div className="output-copy-actions"><button className="mini-button" onClick={() => setEditingCopy((value) => !value)}><PenLine size={12} />{editingCopy ? '结束编辑' : '编辑副本'}</button><button className="mini-button" onClick={validateCopy}><CircleCheck size={12} />校验 JSON</button><button className="mini-button" onClick={() => jsonInputRef.current?.click()}><Upload size={12} />导入 JSON</button><button className="mini-button" onClick={() => downloadCopy(jsonDraft, `kxy-${run.id.slice(0, 8)}-output.json`, 'application/json')}><Download size={12} />下载 JSON</button><button className="mini-button" onClick={() => downloadCopy(textDraft, `kxy-${run.id.slice(0, 8)}-output.txt`, 'text/plain')}><Download size={12} />下载正文</button></div>
          <input ref={jsonInputRef} type="file" hidden accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) importCopy(file); event.target.value = '' }} />
          {copyMessage.tone !== 'idle' && <div className={`schema-message ${copyMessage.tone}`}>{copyMessage.text}</div>}
          <label className="output-copy-field"><span>正文副本</span><textarea rows={5} value={textDraft} readOnly={!editingCopy} onChange={(event) => setTextDraft(event.target.value)} /></label>
          <label className="output-copy-field"><span>JSON 副本</span><textarea rows={8} value={jsonDraft} readOnly={!editingCopy} onChange={(event) => setJsonDraft(event.target.value)} /></label>
          {(acceptedArtifacts.length > 0 || excludedArtifacts.length > 0) && <div className="file-receipt-list"><div className="field-caption">文件接收结果（与实际授权复制一致）</div>{acceptedArtifacts.length > 0 ? <div className="file-receipt accepted"><strong>已接收</strong>{acceptedArtifacts.map((artifact, index) => <span key={`${String(artifact.path)}-${index}`}><Check size={12} />{String(artifact.name || artifact.path)} · {Number(artifact.size || 0)} B</span>)}</div> : <span className="empty-note">没有文件进入容器接收列表。</span>}{excludedArtifacts.length > 0 && <div className="file-receipt excluded"><strong>未接收（仍保留在运行目录）</strong>{excludedArtifacts.map((artifact, index) => <span key={`${String(artifact.path)}-${index}`}><CircleX size={12} />{String(artifact.name || artifact.path)}</span>)}</div>}</div>}
          <details className="output-full-record"><summary>展开完整运行输出映射</summary><pre>{outputSnapshot.slice(0, 20000)}</pre></details>
          {run.output_manifest?.granted_outputs?.map((item) => <small key={item.node_id}>授权输出：{item.path}</small>)}
          {run.output_manifest?.artifacts?.map((artifact) => <a className="artifact-link" key={artifact.path} href={artifact.url.startsWith('http') ? artifact.url : `${API}${artifact.url}`} target="_blank" rel="noreferrer"><Download size={12} />运行目录文件：{artifact.name} · {Math.round(artifact.size / 1024)} KB</a>)}
        </div>}
        {(run.nodes || []).filter((node) => node.output?.text).slice(-3).map((node) => <div className="text-preview" key={`${node.node_id}-text`}><span className="field-caption">{node.node_id} 文本预览</span><p>{String(node.output?.text).slice(0, 2400)}</p></div>)}
        <div className="event-log">{(run.events || []).slice(-12).map((event) => <div key={event.id}><time>{new Date(event.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time><span>{event.type || event.event_type}</span><small>{String(event.payload?.text || event.payload?.message || event.payload?.status || '')}</small></div>)}</div>
      </div> : <div className="run-empty"><ClipboardCheck size={22} /><span>运行会在这里留下节点状态、CLI 日志和最终产物。</span>{history.length > 0 && <div className="run-history">{history.slice(0, 5).map((item) => <button key={item.id} onClick={() => onOpenHistory(item.id)}><span className={`node-status-dot ${item.status}`} />{item.id.slice(0, 8)} · {item.status}</button>)}</div>}</div>}
    </section>
  )
}

function cloneNode(node: KxyNode, patch: Partial<KxyNode> = {}): KxyNode {
  const next = { ...node, ...patch }
  return { ...next, position: { ...(patch.position || node.position) }, data: { ...node.data, ...(patch.data || {}) }, selected: false }
}

function uniqueEdgeId(edges: Edge[], prefix: string): string {
  const used = new Set(edges.map((edge) => edge.id))
  let id = prefix
  let index = 1
  while (used.has(id)) id = `${prefix}-${index++}`
  return id
}

function packSelectedNodes(currentNodes: KxyNode[], currentEdges: Edge[], selectedIds: string[]): { nodes: KxyNode[]; edges: Edge[]; boxId: string } | { error: string } {
  const selected = new Set(selectedIds)
  const unsupported = currentNodes.filter((node) => selected.has(node.id) && ['subflow_input', 'subflow_output', 'blackbox'].includes(String(node.type)))
  if (unsupported.length > 0) return { error: '当前选择包含已有黑盒子或边界标记；请先解包，或只选择要封装的普通节点。' }
  const chosen = currentNodes.filter((node) => selected.has(node.id))
  if (chosen.length === 0) return { error: '请先选择至少一个普通节点。' }
  const incoming = currentEdges.filter((edge) => selected.has(edge.target) && !selected.has(edge.source))
  const outgoing = currentEdges.filter((edge) => selected.has(edge.source) && !selected.has(edge.target))
  if (incoming.length > 1 || outgoing.length > 1) return { error: '当前版本只支持一个 distinct 外部输入和一个 distinct 外部结果；请减少选择范围后再封装。' }
  const incomingTarget = incoming[0] && currentNodes.find((node) => node.id === incoming[0].target)
  if (incomingTarget && ['file', 'text', 'input', 'subflow_input'].includes(String(incomingTarget.type))) return { error: '外部输入不能接入资料/文字源节点；请选择从源节点之后开始的可处理节点。' }
  const minX = Math.min(...chosen.map((node) => node.position.x))
  const minY = Math.min(...chosen.map((node) => node.position.y))
  const boxId = `blackbox-${Math.random().toString(36).slice(2, 8)}`
  const inputId = `${boxId}__input`
  const outputId = `${boxId}__output`
  const nestedNodes: KxyNode[] = [
    { id: inputId, type: 'subflow_input', position: { x: 40, y: Math.max(40, (chosen[0]?.position.y || minY) - minY + BLACKBOX_PAD_Y) }, data: defaultNodeData('subflow_input') },
    ...chosen.map((node) => cloneNode(node, { position: { x: node.position.x - minX + BLACKBOX_PAD_X, y: node.position.y - minY + BLACKBOX_PAD_Y } })),
    { id: outputId, type: 'subflow_output', position: { x: BLACKBOX_PAD_X + 270, y: Math.max(40, (chosen[chosen.length - 1]?.position.y || minY) - minY + BLACKBOX_PAD_Y) }, data: defaultNodeData('subflow_output') },
  ]
  const nestedEdges: Edge[] = currentEdges.filter((edge) => selected.has(edge.source) && selected.has(edge.target)).map((edge) => ({ ...edge }))
  if (incoming[0]) nestedEdges.push({ ...incoming[0], id: `${boxId}__input-edge`, source: inputId, sourceHandle: 'result' })
  if (!incoming[0]) {
    const internalSources = new Set(nestedEdges.map((edge) => edge.target))
    const entry = chosen.find((node) => !['file', 'text', 'input'].includes(String(node.type)) && !internalSources.has(node.id))
    if (entry) nestedEdges.push({ id: `${boxId}__input-edge`, source: inputId, target: entry.id, sourceHandle: 'result', targetHandle: 'items' })
  }
  if (outgoing[0]) nestedEdges.push({ ...outgoing[0], id: `${boxId}__output-edge`, target: outputId, targetHandle: 'items' })
  else {
    const internalTargets = new Set(nestedEdges.filter((edge) => edge.source !== inputId).map((edge) => edge.source))
    const sinks = chosen.filter((node) => !internalTargets.has(node.id))
    sinks.forEach((sink, index) => nestedEdges.push({ id: `${boxId}__output-edge-${index + 1}`, source: sink.id, target: outputId, sourceHandle: 'result', targetHandle: 'items' }))
  }
  const blackbox: KxyNode = {
    id: boxId,
    type: 'blackbox',
    position: { x: minX, y: minY },
    data: { ...defaultNodeData('blackbox'), label: '新黑盒子', workflow: { version: 'kxy.workflow.v1', name: '新黑盒子 内部', nodes: nestedNodes, edges: nestedEdges } },
  }
  const keptNodes = currentNodes.filter((node) => !selected.has(node.id))
  const keptEdges = currentEdges.filter((edge) => !selected.has(edge.source) && !selected.has(edge.target)).map((edge) => ({ ...edge }))
  if (incoming[0]) keptEdges.push({ ...incoming[0], id: uniqueEdgeId(keptEdges, `${boxId}__incoming`), target: boxId, targetHandle: 'items' })
  if (outgoing[0]) keptEdges.push({ ...outgoing[0], id: uniqueEdgeId(keptEdges, `${boxId}__outgoing`), source: boxId, sourceHandle: 'result' })
  return { nodes: [...keptNodes, blackbox], edges: keptEdges, boxId }
}

function unpackBlackbox(currentNodes: KxyNode[], currentEdges: Edge[], boxId: string): { nodes: KxyNode[]; edges: Edge[] } | { error: string } {
  const box = currentNodes.find((node) => node.id === boxId)
  if (!box || box.data.kind !== 'blackbox' || !box.data.workflow) return { error: '选中的节点不是可解包黑盒子。' }
  const nested = flowFromWorkflow(box.data.workflow)
  const input = nested.nodes.find((node) => node.type === 'subflow_input')
  const output = nested.nodes.find((node) => node.type === 'subflow_output')
  if (!input || !output || nested.nodes.filter((node) => node.type === 'subflow_input').length !== 1 || nested.nodes.filter((node) => node.type === 'subflow_output').length !== 1) return { error: '黑盒子必须有且只有一个输入和一个输出边界，无法无损解包。' }
  const inputEdges = nested.edges.filter((edge) => edge.source === input.id)
  const outputEdges = nested.edges.filter((edge) => edge.target === output.id)
  const incoming = currentEdges.filter((edge) => edge.target === box.id)
  const outgoing = currentEdges.filter((edge) => edge.source === box.id)
  if (incoming.length > 1 || outgoing.length > 1) return { error: '黑盒子存在多个外部边界连接，当前版本拒绝解包以避免静默丢边。' }
  if (inputEdges.length > 1 || outputEdges.length > 1) return { error: '黑盒子内部边界存在多个连接，当前版本拒绝解包以避免静默丢边。' }
  const inputEdge = inputEdges[0]
  const outputEdge = outputEdges[0]
  const existingIds = new Set(currentNodes.filter((node) => node.id !== box.id).map((node) => node.id))
  const idMap = new Map<string, string>()
  nested.nodes.filter((node) => ![input.id, output.id].includes(node.id)).forEach((node) => {
    let nextId = node.id
    let index = 1
    while (existingIds.has(nextId) || idMap.has(nextId)) nextId = `${node.id}-${index++}`
    idMap.set(node.id, nextId)
    existingIds.add(nextId)
  })
  const restored = nested.nodes.filter((node) => ![input.id, output.id].includes(node.id)).map((node) => cloneNode(node, { id: idMap.get(node.id) || node.id, position: { x: box.position.x + node.position.x - BLACKBOX_PAD_X, y: box.position.y + node.position.y - BLACKBOX_PAD_Y } }))
  const baseEdges = currentEdges.filter((edge) => edge.source !== box.id && edge.target !== box.id).map((edge) => ({ ...edge }))
  const nestedInternal = nested.edges.filter((edge) => edge.source !== input.id && edge.target !== output.id).map((edge, index) => ({ ...edge, id: uniqueEdgeId([...baseEdges, ...nested.edges.slice(0, index)], `${box.id}__inner-${index + 1}`), source: idMap.get(edge.source) || edge.source, target: idMap.get(edge.target) || edge.target }))
  const rebuiltEdges = [...baseEdges, ...nestedInternal]
  const directPassThrough = inputEdge && outputEdge && inputEdge.target === output.id && outputEdge.source === input.id
  if (directPassThrough && incoming[0] && outgoing[0]) rebuiltEdges.push({ ...incoming[0], id: uniqueEdgeId(rebuiltEdges, `${box.id}__pass-through`), target: outgoing[0].target, targetHandle: outgoing[0].targetHandle || 'items' })
  else {
    if (incoming[0] && inputEdge && inputEdge.target !== output.id) rebuiltEdges.push({ ...incoming[0], id: uniqueEdgeId(rebuiltEdges, `${box.id}__incoming`), target: idMap.get(inputEdge.target) || inputEdge.target, targetHandle: inputEdge.targetHandle || 'items' })
    if (outgoing[0] && outputEdge && outputEdge.source !== input.id) rebuiltEdges.push({ ...outgoing[0], id: uniqueEdgeId(rebuiltEdges, `${box.id}__outgoing`), source: idMap.get(outputEdge.source) || outputEdge.source, sourceHandle: outputEdge.sourceHandle || 'result' })
  }
  return { nodes: [...currentNodes.filter((node) => node.id !== box.id), ...restored], edges: rebuiltEdges }
}

function cloneNodesForHistory(items: KxyNode[]): KxyNode[] {
  return items.map((node) => {
    const clone = JSON.parse(JSON.stringify(node)) as KxyNode
    delete (clone as KxyNode & { width?: number }).width
    delete (clone as KxyNode & { height?: number }).height
    delete (clone as KxyNode & { measured?: unknown }).measured
    delete (clone as KxyNode & { initialWidth?: number }).initialWidth
    delete (clone as KxyNode & { initialHeight?: number }).initialHeight
    delete (clone as KxyNode & { resizing?: boolean }).resizing
    delete (clone as KxyNode & { dragging?: boolean }).dragging
    clone.selected = false
    return clone
  })
}

function updateSkillReferencesInNodes(items: KxyNode[], shouldKeep: (id: string) => boolean): KxyNode[] {
  let changed = false
  const nextItems = items.map((node) => {
    let nextData = node.data
    let nodeChanged = false
    if (Array.isArray(node.data.skill_ids)) {
      const nextSkillIds = node.data.skill_ids.filter(shouldKeep)
      if (nextSkillIds.length !== node.data.skill_ids.length || nextSkillIds.some((id, index) => id !== node.data.skill_ids?.[index])) {
        nextData = { ...nextData, skill_ids: nextSkillIds }
        nodeChanged = true
      }
    }
    const workflow = node.data.workflow
    if (workflow && typeof workflow === 'object' && Array.isArray(workflow.nodes)) {
      const nextNodes = updateSkillReferencesInNodes(workflow.nodes, shouldKeep)
      if (nextNodes !== workflow.nodes) {
        nextData = { ...nextData, workflow: { ...workflow, nodes: nextNodes } }
        nodeChanged = true
      }
    }
    if (!nodeChanged) return node
    changed = true
    return { ...node, data: nextData }
  })
  return changed ? nextItems : items
}

export default function App() {
  const { appearance, setAppearance } = useUiStore()
  const [workflowName, setWorkflowName] = useState(defaultWorkflow.name)
  const [workflowId, setWorkflowId] = useState(defaultWorkflow.id)
  const [nodes, setNodes, applyNodesChange] = useNodesState<KxyNode>(defaultWorkflow.nodes)
  const [edges, setEdges, applyEdgesChange] = useEdgesState(defaultWorkflow.edges)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [interactionMode, setInteractionMode] = useState<'pan' | 'select'>('pan')
  const [canvasStack, setCanvasStack] = useState<Array<{ nodeId: string; name: string; workflowId?: string; nodes: KxyNode[]; edges: Edge[] }>>([])
  const [files, setFiles] = useState<FileAsset[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [skillHubScan, setSkillHubScan] = useState<SkillHubScan | null>(null)
  const [skillHubScanBusy, setSkillHubScanBusy] = useState(false)
  const [skillHubSyncBusy, setSkillHubSyncBusy] = useState(false)
  const [presets, setPresets] = useState<ComponentPreset[]>([])
  const [savedWorkflows, setSavedWorkflows] = useState<WorkflowRecord[]>([])
  const [runHistory, setRunHistory] = useState<RunSummary[]>([])
  const [grants, setGrants] = useState<Array<{ id: string; canonical_path: string; revoked_at?: string | null }>>([])
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [agents, setAgents] = useState<AgentProfile[]>(mergeAgentProfiles([]))
  const [models, setModels] = useState<AgentModel[]>([])
  const [defaultAnalyzer, setDefaultAnalyzer] = useState<DefaultAnalyzerSetting>(DEFAULT_ANALYZER_SETTING)
  const [outputDefaults, setOutputDefaults] = useState<OutputDefaults>(DEFAULT_OUTPUT_DEFAULTS)
  const [agentCheckOnSettingsOpen, setAgentCheckOnSettingsOpen] = useState(false)
  const [autoCheckMounts, setAutoCheckMounts] = useState(true)
  const [workspaceDefaultsReady, setWorkspaceDefaultsReady] = useState(false)
  const [fonts, setFonts] = useState<LocalFont[]>([])
  const [mcps, setMcps] = useState<McpRecord[]>([])
  const [backgroundUrl, setBackgroundUrl] = useState('')
  const [templates, setTemplates] = useState<Workflow[]>([])
  const [cliStatus, setCliStatus] = useState<CliStatus[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [runOpen, setRunOpen] = useState(true)
  const [notice, setNotice] = useState<{ type: 'ok' | 'error'; text: string } | null>(null)
  const [logoFailed, setLogoFailed] = useState(false)
  const [mobilePanel, setMobilePanel] = useState<'left' | 'right' | null>(null)
  const [leftPanelOpen, setLeftPanelOpen] = useState(true)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [historyCount, setHistoryCount] = useState(0)
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<KxyNode, Edge> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const importInputRef = useRef<HTMLInputElement>(null)
  const portableImportInputRef = useRef<HTMLInputElement>(null)
  const portableMissingFileInputRef = useRef<HTMLInputElement>(null)
  const portableCommitBusyRef = useRef(false)
  const [portableExportOpen, setPortableExportOpen] = useState(false)
  const [portableExportFileIds, setPortableExportFileIds] = useState<string[]>([])
  const [portableExportSkillIds, setPortableExportSkillIds] = useState<string[]>([])
  const [portableImportOpen, setPortableImportOpen] = useState(false)
  const [portableImportBusy, setPortableImportBusy] = useState(false)
  const [portablePreview, setPortablePreview] = useState<PortablePreview | null>(null)
  const [portableBindings, setPortableBindings] = useState<PortableBindings>(emptyPortableBindings)
  const [portableImportFile, setPortableImportFile] = useState<File | null>(null)
  const [portableMissingFileSourceId, setPortableMissingFileSourceId] = useState<string | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  const viewedRunIdRef = useRef<string | null>(null)
  const terminalRunIdRef = useRef<string | null>(null)
  const runSyncInFlightRef = useRef(false)
  const flowFrameRef = useRef<HTMLDivElement>(null)
  const agentRefreshRevisionRef = useRef<Record<string, number>>({})
  const agentsRef = useRef<AgentProfile[]>(agents)
  agentsRef.current = agents
  const historyRef = useRef<EditorSnapshot[]>([])
  const credentialMutationRevisionRef = useRef(0)
  const modelMutationRevisionRef = useRef(0)
  const analyzerMutationRevisionRef = useRef(0)
  const draggingNodeRef = useRef(false)
  const lastTypingRef = useRef<{ key: string; at: number } | null>(null)

  const selectedNode = nodes.find((node) => node.id === selectedId)
  const selectedNodePath = selectedNode ? [...canvasStack.map((frame) => frame.nodeId), selectedNode.id].join('/') : ''
  const incomingSources = useMemo(() => selectedNode ? edges.filter((edge) => edge.target === selectedNode.id).map((edge) => nodes.find((node) => node.id === edge.source)).filter((node): node is KxyNode => Boolean(node)) : [], [edges, nodes, selectedNode])
  const conditionSample = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'condition') return undefined
    const source = incomingSources[0]
    if (!source) return undefined
    const runtime = run?.nodes?.find((item) => item.node_id === source.id || item.node_path === [...canvasStack.map((frame) => frame.nodeId), source.id].join('/'))?.output
    if (!runtime) return undefined
    return { source: source.data.label || source.id, value: runtime, fields: flattenSampleFields(runtime) }
  }, [canvasStack, incomingSources, run, selectedNode])
  const filterItems = useMemo(() => {
    if (!selectedNode || selectedNode.type !== 'filter') return []
    const values: unknown[] = []
    incomingSources.forEach((source) => {
      const path = [...canvasStack.map((frame) => frame.nodeId), source.id].join('/')
      const runtime = run?.nodes?.find((item) => item.node_id === source.id || item.node_path === path)?.output
      if (runtime) {
        values.push(runtime)
        return
      }
      if (source.type === 'input') {
        const attachments = (source.data.attachments || []).map((attachment) => {
          const asset = files.find((item) => item.id === attachment.file_id)
          return { status: 'source', active: true, file_id: attachment.file_id, name: attachment.name || attachment.display_name, display_name: attachment.display_name, relative_path: attachment.relative_path, sha256: asset?.sha256, mime: asset?.mime, size: asset?.size }
        })
        values.push({ status: 'source', active: true, text: source.data.text || '', input_text: source.data.text || '', items: attachments })
      } else if (source.type === 'file') {
        values.push({ status: 'source', active: true, file_id: source.data.file_id, name: source.data.fileName, display_name: source.data.fileName, relative_path: source.data.fileName })
      } else if (source.type === 'text') {
        values.push({ status: 'source', active: true, text: source.data.text || '', name: source.data.label })
      }
    })
    return values
  }, [canvasStack, files, incomingSources, run, selectedNode])
  const displayNodes = useMemo(() => nodes.map((node) => {
    const executionNode = run?.nodes?.find((item) => item.node_id === node.id)
    const nodePath = [...canvasStack.map((frame) => frame.nodeId), node.id].join('/')
    const loopRound = run?.loop_rounds?.filter((item) => item.loop_path === nodePath).slice(-1)[0]
    const skillNames = (node.data.skill_ids || []).map((id) => skills.find((skill) => skill.id === id)?.name).filter((name): name is string => Boolean(name))
    return { ...node, selected: selectedIds.includes(node.id), data: { ...node.data, runtime_status: executionNode?.status || '', loop_status: loopRound?.status || '', loop_round: loopRound?.round_no, skill_names: skillNames } }
  }), [canvasStack, nodes, run, selectedIds, skills])
  const nodeTypes = useMemo(() => ({ file: NodeCard, text: NodeCard, input: NodeCard, filter: NodeCard, analyzer: NodeCard, condition: NodeCard, container: NodeCard, human: NodeCard, blackbox: NodeCard, subflow_input: NodeCard, subflow_output: NodeCard, default: NodeCard }), [])
  const cssVars = {
    '--kxy-accent': appearance.accent,
    '--kxy-canvas': appearance.canvas,
    '--kxy-font': appearance.custom_font || undefined,
    '--kxy-text-font': appearance.text_font || appearance.custom_font || undefined,
    '--kxy-code-font': appearance.code_font || undefined,
    '--kxy-font-size': `${appearance.font_size || 14}px`,
    '--kxy-code-font-size': `${appearance.code_font_size || 13}px`,
    '--kxy-background-image': backgroundUrl ? `url("${backgroundUrl}")` : 'none',
  } as React.CSSProperties

  const showNotice = useCallback((type: 'ok' | 'error', text: string) => {
    setNotice({ type, text })
    window.setTimeout(() => setNotice(null), 4200)
  }, [])

  const clearRunView = useCallback(() => {
    eventSourceRef.current?.close()
    eventSourceRef.current = null
    activeRunIdRef.current = null
    viewedRunIdRef.current = null
    terminalRunIdRef.current = null
    runSyncInFlightRef.current = false
    setRun(null)
  }, [])

  const editorStateRef = useRef({ nodes, edges, canvasStack, workflowName, workflowId })
  editorStateRef.current = { nodes, edges, canvasStack, workflowName, workflowId }
  const composedRootWorkflow = useMemo(
    () => composeRootWorkflow(workflowName, workflowId, nodes, edges, canvasStack),
    [canvasStack, edges, nodes, workflowId, workflowName],
  )
  const historyLimitRef = useRef(5)
  historyLimitRef.current = Math.max(1, Math.min(50, Number(appearance.undo_limit) || 5))
  const structuralHistoryAtRef = useRef(0)

  const makeSnapshot = useCallback((sourceNodes?: KxyNode[], sourceEdges?: Edge[], sourceStack?: EditorSnapshot['canvasStack'], sourceName?: string, sourceId?: string): EditorSnapshot => {
    const current = editorStateRef.current
    const graphNodes = sourceNodes || current.nodes
    const graphEdges = sourceEdges || current.edges
    const stack = sourceStack || current.canvasStack
    return {
      workflowName: sourceName ?? current.workflowName,
      workflowId: sourceId ?? current.workflowId,
      nodes: cloneNodesForHistory(graphNodes),
      edges: JSON.parse(JSON.stringify(graphEdges)) as Edge[],
      canvasStack: stack.map((frame) => ({ ...frame, nodes: cloneNodesForHistory(frame.nodes), edges: JSON.parse(JSON.stringify(frame.edges)) as Edge[] })),
    }
  }, [])

  const recordHistory = useCallback((snapshot?: EditorSnapshot, key?: string) => {
    const now = Date.now()
    if (key && lastTypingRef.current?.key === key && now - lastTypingRef.current.at < 700) {
      lastTypingRef.current = { key, at: now }
      return
    }
    lastTypingRef.current = key ? { key, at: now } : null
    const next = [...historyRef.current, snapshot || makeSnapshot()].slice(-historyLimitRef.current)
    historyRef.current = next
    setHistoryCount(next.length)
  }, [makeSnapshot])

  const undo = useCallback(() => {
    const snapshot = historyRef.current.pop()
    if (!snapshot) return
    setNodes(cloneNodesForHistory(snapshot.nodes))
    setEdges(JSON.parse(JSON.stringify(snapshot.edges)) as Edge[])
    setCanvasStack(snapshot.canvasStack.map((frame) => ({ ...frame, nodes: cloneNodesForHistory(frame.nodes), edges: JSON.parse(JSON.stringify(frame.edges)) as Edge[] })))
    setWorkflowName(snapshot.workflowName)
    setWorkflowId(snapshot.workflowId)
    setSelectedId(null)
    setSelectedIds([])
    lastTypingRef.current = null
    setHistoryCount(historyRef.current.length)
    showNotice('ok', '已撤回上一步图编辑；运行、外部副作用和设置不会被撤回')
  }, [setEdges, setNodes, showNotice])

  useEffect(() => {
    const limit = Math.max(1, Math.min(50, Number(appearance.undo_limit) || 5))
    if (historyRef.current.length > limit) {
      historyRef.current = historyRef.current.slice(-limit)
      setHistoryCount(historyRef.current.length)
    }
  }, [appearance.undo_limit])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z' || event.shiftKey) return
      const target = event.target as HTMLElement | null
      if (target?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName || '')) return
      event.preventDefault()
      undo()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [undo])

  const refreshResources = useCallback(async () => {
    const credentialRevisionAtStart = credentialMutationRevisionRef.current
    const modelRevisionAtStart = modelMutationRevisionRef.current
    const analyzerRevisionAtStart = analyzerMutationRevisionRef.current
    const [fileList, skillList, presetList, grantList, workflowList, runs, credentialList, cli, agentPayload, modelPayload, fontPayload, mcpList] = await Promise.all([
      apiOr<FileAsset[]>('/api/files', []),
      apiOr<Skill[]>('/api/skills', []),
      apiOr<ComponentPreset[]>('/api/presets', []),
      apiOr<Array<{ id: string; canonical_path: string; revoked_at?: string | null }>>('/api/grants', []),
      apiOr<WorkflowRecord[]>('/api/workflows', []),
      apiOr<RunSummary[]>('/api/runs', []),
      apiOr<Credential[]>('/api/credentials', []),
      apiOr<{ clis?: CliStatus[] }>('/api/cli/status', {}),
      apiOr<AgentProfile[] | { agents?: AgentProfile[] }>('/api/agents', []),
      apiOr<AgentModel[] | { models?: AgentModel[] }>('/api/agent-models', []),
      apiOr<{ fonts?: LocalFont[]; source?: string; error?: string }>('/api/fonts', { fonts: [] }),
      apiOr<McpRecord[]>('/api/mcps', []),
    ])
    const rawAgents = Array.isArray(agentPayload) ? agentPayload : agentPayload.agents || []
    const rawModels = Array.isArray(modelPayload) ? modelPayload : modelPayload.models || []
    setFiles(fileList); setSkills(skillList); if (analyzerMutationRevisionRef.current === analyzerRevisionAtStart) setPresets(presetList); setGrants(grantList); setSavedWorkflows(workflowList.map((item) => ({ ...item, workflow: flowFromWorkflow(item.workflow) }))); setRunHistory(runs)
    if (credentialMutationRevisionRef.current === credentialRevisionAtStart) setCredentials(credentialList)
    setCliStatus(cli.clis || []); setAgents(mergeAgentProfiles(rawAgents)); if (modelMutationRevisionRef.current === modelRevisionAtStart) setModels(rawModels); setFonts(fontPayload.fonts || []); setMcps(mcpList)
  }, [showNotice])

  const removeSkillReferences = useCallback((skillIds: Iterable<string>) => {
    const removed = new Set(skillIds)
    if (removed.size === 0) return
    const shouldKeep = (id: string) => !removed.has(id)
    setNodes((current) => updateSkillReferencesInNodes(current, shouldKeep))
    setCanvasStack((current) => current.map((frame) => {
      const nextNodes = updateSkillReferencesInNodes(frame.nodes, shouldKeep)
      return nextNodes === frame.nodes ? frame : { ...frame, nodes: nextNodes }
    }))
  }, [setCanvasStack, setNodes])

  const applyServerSkills = useCallback((latest: Skill[]) => {
    setSkills(latest)
  }, [])

  const refreshSkillList = useCallback(async () => {
    const latest = await api<Skill[]>('/api/skills')
    applyServerSkills(latest)
    return latest
  }, [applyServerSkills])

  const scanSkillHubIndex = useCallback(async () => {
    if (skillHubScanBusy) return
    setSkillHubScanBusy(true)
    try {
      setSkillHubScan(await api<SkillHubScan>('/api/skillhub/index/scan'))
      showNotice('ok', 'SkillHub 中央索引已扫描；未执行任何同步动作')
    } catch (error) {
      showNotice('error', `SkillHub 索引扫描失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSkillHubScanBusy(false)
    }
  }, [showNotice, skillHubScanBusy])

  const syncSkillHubIndex = useCallback(async (items: Array<{ key: string; action: SkillHubSyncAction; fingerprint: string }>) => {
    if (items.length === 0 || skillHubSyncBusy) return { status: 'blocked', results: [] }
    setSkillHubSyncBusy(true)
    try {
      const result = await api<SkillHubSyncResult>('/api/skillhub/index/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      })
      let refreshFailed = false
      const refreshFailureReasons: string[] = []
      try {
        await refreshSkillList()
      } catch (error) {
        refreshFailed = true
        refreshFailureReasons.push(`资源列表刷新：${error instanceof Error ? error.message : String(error)}`)
      }
      try {
        setSkillHubScan(await api<SkillHubScan>('/api/skillhub/index/scan'))
      } catch (error) {
        refreshFailed = true
        refreshFailureReasons.push(`索引重新扫描：${error instanceof Error ? error.message : String(error)}`)
      }
      const updated = result.results.filter((item) => item.status === 'updated').length
      const failed = result.results.length - updated
      const failureReasons = result.results
        .filter((item) => item.status !== 'updated')
        .map((item) => `${item.key || '项目'}：${item.reason || '未知原因'}`)
        .join('；')
      if (refreshFailed) {
        const details = [...refreshFailureReasons, ...(failed > 0 ? [`同步失败：${failureReasons}`] : [])].join('；')
        showNotice('error', `SkillHub 已处理 ${updated} 项，但刷新或部分同步失败：${details || '未知原因'}；请重新扫描`)
      } else if (failed > 0) {
        showNotice('error', `SkillHub 已处理 ${updated} 项，${failed} 项未处理：${failureReasons}。请按最新扫描结果复核`)
      } else {
        showNotice('ok', `SkillHub 已同步 ${updated} 项；恢复动作必须单独选择`)
      }
      return result
    } catch (error) {
      showNotice('error', `SkillHub 同步失败：${error instanceof Error ? error.message : String(error)}`)
      throw error
    } finally {
      setSkillHubSyncBusy(false)
    }
  }, [refreshSkillList, showNotice, skillHubSyncBusy])

  const bulkDeleteSkills = useCallback(async (skillIds: string[]): Promise<BulkDeleteResult> => {
    let result: BulkDeleteResult
    try {
      result = await api<BulkDeleteResult>('/api/skills/bulk-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_ids: skillIds }),
      })
    } catch (error) {
      showNotice('error', `批量删除失败：${error instanceof Error ? error.message : String(error)}`)
      throw error
    }
    const actuallyDeleted = [
      ...(result.deleted || []),
      ...(result.failed || []).filter((item) => item.deleted).map((item) => item.id),
    ]
    const uniqueActuallyDeleted = [...new Set(actuallyDeleted)]
    setSkillHubScan(null)
    removeSkillReferences(uniqueActuallyDeleted)
    let refreshError: unknown = null
    try {
      await refreshSkillList()
    } catch (error) {
      refreshError = error
      // The returned deleted flags are authoritative for the local UI even if
      // the follow-up list request is temporarily unavailable.
      setSkills((current) => current.filter((skill) => !uniqueActuallyDeleted.includes(skill.id)))
    }
    const cleanupFailures = (result.failed || []).filter((item) => item.deleted)
    const hardFailures = (result.failed || []).filter((item) => !item.deleted)
    const reasons = (items: Array<{ id: string; reason?: string; deleted?: boolean }>) => items.map((item) => `${item.id}：${item.reason || '未知原因'}`).join('；')
    if (cleanupFailures.length > 0) {
      showNotice('error', `${cleanupFailures.length} 个 Skill 记录已删除，但快照清理失败：${reasons(cleanupFailures)}。${hardFailures.length > 0 ? `另有 ${hardFailures.length} 项未删除：${reasons(hardFailures)}。` : ''}`)
    } else if (hardFailures.length > 0) {
      showNotice('error', `${hardFailures.length} 个 Skill 删除失败，仍保留在列表中：${reasons(hardFailures)}。`)
    } else if (refreshError) {
      showNotice('error', `已删除 ${uniqueActuallyDeleted.length} 个 Skill 快照，但列表刷新失败：${refreshError instanceof Error ? refreshError.message : String(refreshError)}；请重新扫描资源`)
    } else if (uniqueActuallyDeleted.length > 0) {
      showNotice('ok', `已删除 ${uniqueActuallyDeleted.length} 个 Skill 快照；历史运行快照不受影响`)
    }
    return result
  }, [refreshSkillList, removeSkillReferences, showNotice])

  const refreshRunHistory = useCallback(async () => {
    try {
      setRunHistory(await api<RunSummary[]>('/api/runs'))
    } catch (error) {
      showNotice('error', `运行历史读取失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [showNotice])

  const pickPath = useCallback(async (kind: 'file' | 'folder'): Promise<string | null> => {
    try {
      const result = await api<{ cancelled: boolean; path?: string }>('/api/picker', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind }) })
      if (result.cancelled || !result.path) {
        showNotice('ok', '已取消选择，原配置未改变')
        return null
      }
      return result.path
    } catch (error) {
      showNotice('error', `原生选择器不可用：${error instanceof Error ? error.message : String(error)}`)
      return null
    }
  }, [showNotice])

  const saveAgent = useCallback(async (agent: AgentProfile) => {
    const saved = await api<AgentProfile>(`/api/agents/${encodeURIComponent(agent.id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ executable: agent.executable, skill_roots: agent.skill_roots, runtime_interpreter: agent.runtime_interpreter || null }) })
    setAgents((current) => mergeAgentProfiles(current.map((item) => item.id === agent.id ? { ...item, ...saved, executable: saved.executable ?? agent.executable, skill_roots: saved.skill_roots ?? agent.skill_roots } : item)))
  }, [])

  const probeAgentRuntime = useCallback(async (id: string, interpreter?: string): Promise<AgentProfile> => {
    const result = await api<{ agent_id: string; required?: boolean; status?: string; interpreter?: string | null; interpreter_version?: string | null; version?: string | null; message?: string | null }>(`/api/agents/${encodeURIComponent(id)}/runtime-probe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...(interpreter ? { runtime_interpreter: interpreter } : {}) }),
    })
    const runtime = {
      interpreter: result.interpreter ?? null,
      interpreter_version: result.interpreter_version ?? null,
      status: result.status || 'unknown',
      version: result.version ?? null,
      checked_at: new Date().toISOString(),
      message: result.message ?? null,
    }
    const existing = agentsRef.current.find((item) => item.id === id) || mergeAgentProfiles([]).find((item) => item.id === id)
    const profile = { ...(existing || { id, label: id, executable: '', skill_roots: [], available: false, status: 'UNKNOWN' }), runtime, runtime_interpreter: result.interpreter ?? interpreter ?? null } as AgentProfile
    setAgents((current) => mergeAgentProfiles(current.map((item) => item.id === id ? { ...item, runtime, runtime_interpreter: result.interpreter ?? interpreter ?? null } : item)))
    return profile
  }, [])

  const discoverAgent = useCallback(async (id: string): Promise<AgentProfile | null> => {
    const revision = (agentRefreshRevisionRef.current[id] || 0) + 1
    agentRefreshRevisionRef.current[id] = revision
    const result = await api<AgentProfile | { profile?: AgentProfile }>(`/api/agents/${encodeURIComponent(id)}/discover`, { method: 'POST' })
    const profile: AgentProfile | undefined = typeof result === 'object' && result !== null && 'profile' in result ? result.profile : result as AgentProfile
    if (!profile) return null
    if (agentRefreshRevisionRef.current[id] !== revision) return profile
    setAgents((current) => mergeAgentProfiles(current.map((item) => item.id === id ? { ...item, ...profile } : item)))
    const discoveredModels = profile.models || []
    modelMutationRevisionRef.current += 1
    setModels((current) => {
      const preserved = current.filter((item) => {
        const belongsToAgent = (item.agent_id || item.cli_id) === id
        return !belongsToAgent || item.source !== 'native' || Boolean(item.native_model_ref)
      })
      const known = new Set(preserved.map((item) => item.id))
      const refreshedNative = discoveredModels.filter((item) => item.source === 'native' && !item.native_model_ref)
      const missingConfigured = discoveredModels.filter((item) => item.source !== 'native' || Boolean(item.native_model_ref)).filter((item) => !known.has(item.id))
      return [...preserved, ...refreshedNative, ...missingConfigured]
    })
    return profile
  }, [])

  const refreshAgents = useCallback(async (): Promise<{ succeeded: number; failed: number }> => {
    const targetIds = agentsRef.current.map((agent) => String(agent.id))
    const revisions = Object.fromEntries(targetIds.map((id) => {
      const revision = (agentRefreshRevisionRef.current[id] || 0) + 1
      agentRefreshRevisionRef.current[id] = revision
      return [id, revision]
    }))
    const result = await api<{ agents?: AgentProfile[]; results?: Array<{ id: string; ok: boolean; partial?: boolean; error?: string }> }>('/api/agents/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
    const refreshed = (result.agents || []).filter((profile) => revisions[String(profile.id)] === agentRefreshRevisionRef.current[String(profile.id)])
    if (refreshed.length > 0) {
      setAgents((current) => mergeAgentProfiles(current.map((item) => refreshed.find((profile) => profile.id === item.id) ? { ...item, ...refreshed.find((profile) => profile.id === item.id) } : item)))
      modelMutationRevisionRef.current += 1
      setModels((current) => refreshed.reduce((items, profile) => {
        const id = profile.id
        const preserved = items.filter((item) => (item.agent_id || item.cli_id) !== id || item.source !== 'native' || Boolean(item.native_model_ref))
        const known = new Set(preserved.map((item) => item.id))
        const native = (profile.models || []).filter((item) => item.source === 'native' && !item.native_model_ref)
        const configured = (profile.models || []).filter((item) => item.source !== 'native' || Boolean(item.native_model_ref)).filter((item) => !known.has(item.id))
        return [...preserved, ...native, ...configured]
      }, current))
    }
    const results = result.results || []
    return { succeeded: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length }
  }, [])

  const scanAgentSkills = useCallback(async (id: string): Promise<unknown[]> => {
    const result = await api<unknown[] | { skills?: unknown[] }>(`/api/agents/${encodeURIComponent(id)}/skills`)
    return Array.isArray(result) ? result : result.skills || []
  }, [])

  const importAgentSkills = useCallback(async (id: string, paths: string[]) => {
    const result = await api<{ imported?: Skill[]; errors?: string[] }>(`/api/agents/${encodeURIComponent(id)}/skills/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paths }) })
    if (result.imported?.length) setSkills((current) => [...result.imported!, ...current.filter((skill) => !result.imported!.some((item) => item.id === skill.id))])
    return result
  }, [])

  const discoverAgentMcps = useCallback(async (id: string): Promise<McpCandidate[]> => {
    const result = await api<McpCandidate[] | { mcps?: McpCandidate[] }>(`/api/agents/${encodeURIComponent(id)}/mcps`)
    return Array.isArray(result) ? result : result.mcps || []
  }, [])

  const importAgentMcps = useCallback(async (id: string, ids: string[]) => {
    const result = await api<{ imported?: McpRecord[]; errors?: string[] }>(`/api/agents/${encodeURIComponent(id)}/mcps/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) })
    if (result.imported?.length) setMcps((current) => [...result.imported!, ...current.filter((item) => !result.imported!.some((newItem) => newItem.id === item.id))])
    return result
  }, [])

  const previewSkillMount = useCallback(async (agentId: string, skillIds: string[]) => {
    return api<{ status?: string; skills?: Array<{ skill_id?: string; status?: string; message?: string; cross_agent?: boolean }> }>('/api/skillhub/mount', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent_id: agentId, skill_ids: skillIds }) })
  }, [])

  const checkSkillDependencies = useCallback(async (payload: { agent_id: string; skill_ids: string[]; force?: boolean; model_ref?: string; credential_id?: string; model?: string; source?: string; mcp_ids?: string[] }): Promise<DependencyCheckResponse> => {
    return api<DependencyCheckResponse>('/api/skillhub/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  }, [])

  const setSkillDependencies = useCallback(async (skillId: string, dependencies: Record<string, unknown>): Promise<DependencySkillResult> => {
    return api<DependencySkillResult>('/api/skillhub/dependencies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ skill_id: skillId, dependencies }) })
  }, [])

  const listDependencyChecks = useCallback(async (skillId?: string): Promise<DependencyCacheRecord[]> => {
    const query = skillId ? `?skill_id=${encodeURIComponent(skillId)}` : ''
    return api<DependencyCacheRecord[]>(`/api/skillhub/checks${query}`)
  }, [])

  const clearDependencyChecks = useCallback(async (skillId?: string): Promise<number> => {
    const query = skillId ? `?skill_id=${encodeURIComponent(skillId)}` : ''
    const result = await api<{ ok?: boolean; cleared?: number }>(`/api/skillhub/checks${query}`, { method: 'DELETE' })
    return Number(result.cleared || 0)
  }, [])

  const createModel = useCallback(async (payload: AgentModelInput): Promise<AgentModel> => {
    if (payload.source === 'native') throw new Error('原生模型只能来自 Agent 发现结果；请使用 API 或手动来源')
    const model = await api<AgentModel>('/api/agent-models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    modelMutationRevisionRef.current += 1
    setModels((current) => [model, ...current.filter((item) => item.id !== model.id)])
    return model
  }, [])

  const updateModel = useCallback(async (id: string, payload: Partial<AgentModel>): Promise<AgentModel> => {
    const existing = models.find((item) => item.id === id)
    if (payload.source === 'native' && existing?.source !== 'native') throw new Error('原生模型来源不能通过手动编辑伪造')
    const model = await api<AgentModel>(`/api/agent-models/${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    modelMutationRevisionRef.current += 1
    setModels((current) => current.map((item) => item.id === id ? model : item))
    return model
  }, [models])

  const deleteModel = useCallback(async (id: string) => {
    await api(`/api/agent-models/${encodeURIComponent(id)}`, { method: 'DELETE' })
    modelMutationRevisionRef.current += 1
    setModels((current) => current.filter((item) => item.id !== id))
    showNotice('ok', '模型记录已删除；使用它的节点需要重新绑定')
  }, [showNotice])

  const syncRun = useCallback(async (runId: string, source?: EventSource) => {
    if (activeRunIdRef.current !== runId || terminalRunIdRef.current === runId) return
    if (runSyncInFlightRef.current) return
    runSyncInFlightRef.current = true
    try {
      const next = await api<Run>(`/api/runs/${runId}`)
      if (activeRunIdRef.current !== runId) return
      if (viewedRunIdRef.current === runId) setRun(next)
      if (['succeeded', 'failed', 'cancelled', 'rejected', 'interrupted'].includes(next.status)) {
        terminalRunIdRef.current = runId
        source?.close()
        if (eventSourceRef.current === source) eventSourceRef.current = null
        void refreshRunHistory()
      }
    } catch {
      // The next event or history poll can retry without producing a log storm.
    } finally {
      runSyncInFlightRef.current = false
    }
  }, [refreshRunHistory])

  useEffect(() => {
    void (async () => {
      try {
        const [settings, templateList] = await Promise.all([api<SettingsResponse>('/api/settings'), api<Workflow[]>('/api/templates')])
        const rawMotionIntensity = Number(settings.motion_intensity)
        const normalizedSettings: Appearance = { ...DEFAULT_APPEARANCE, palette: settings.palette || DEFAULT_APPEARANCE.palette, accent: settings.accent || DEFAULT_APPEARANCE.accent, canvas: settings.canvas || DEFAULT_APPEARANCE.canvas, font: settings.font || DEFAULT_APPEARANCE.font, custom_font: settings.custom_font || '', text_font: settings.text_font || settings.custom_font || '', code_font: settings.code_font || '', background_image: settings.background_image || '', font_size: Number(settings.font_size) || DEFAULT_APPEARANCE.font_size, code_font_size: Number(settings.code_font_size) || DEFAULT_APPEARANCE.code_font_size, motion_enabled: settings.motion_enabled !== false && String(settings.motion_enabled) !== 'false', motion_intensity: Number.isFinite(rawMotionIntensity) ? Math.max(0, Math.min(500, rawMotionIntensity)) : DEFAULT_APPEARANCE.motion_intensity, undo_limit: Math.max(1, Math.min(50, Number(settings.undo_limit) || DEFAULT_APPEARANCE.undo_limit)) }
        const savedDefault = settings.default_analyzer
        const savedOutput = settings.output_defaults
        setAppearance(normalizedSettings)
        setDefaultAnalyzer(savedDefault && typeof savedDefault === 'object' ? { ...DEFAULT_ANALYZER_SETTING, ...savedDefault } : DEFAULT_ANALYZER_SETTING)
        const normalizedOutputDefaults: OutputDefaults = savedOutput && typeof savedOutput === 'object' ? { export_formats: [...(savedOutput.export_formats || [])], allowed_file_extensions: [...(savedOutput.allowed_file_extensions || [])], json_mode: savedOutput.json_mode === 'content' ? 'content' : 'full' } : DEFAULT_OUTPUT_DEFAULTS
        setOutputDefaults(normalizedOutputDefaults)
        setAgentCheckOnSettingsOpen(settings.agent_check_on_settings_open === true || String(settings.agent_check_on_settings_open) === 'true')
        setAutoCheckMounts(settings.auto_check_mounts !== false && String(settings.auto_check_mounts) !== 'false')
        setWorkspaceDefaultsReady(true)
        setBackgroundUrl(normalizedSettings.background_image ? `${API}/api/appearance/background/${encodeURIComponent(normalizedSettings.background_image)}` : ''); setTemplates(templateList.map(flowFromWorkflow))
      } catch (error) {
        setWorkspaceDefaultsReady(false)
        showNotice('error', `后端尚未就绪：${error instanceof Error ? error.message : String(error)}`)
      }
      await refreshResources()
    })()
    return () => {
      activeRunIdRef.current = null
      eventSourceRef.current?.close()
    }
  }, [refreshResources, setAppearance, showNotice])

  const updateNode = useCallback((patch: Partial<KxyNodeData>) => {
    if (!selectedId) return
    recordHistory(makeSnapshot(), `node-edit:${selectedId}:${Object.keys(patch).sort().join(',')}`)
    setNodes((current) => current.map((node) => node.id === selectedId ? { ...node, data: { ...node.data, ...patch } } : node))
  }, [selectedId, setNodes])

  const recordStructuralHistory = () => {
    const now = performance.now()
    if (now - structuralHistoryAtRef.current < 60) return
    structuralHistoryAtRef.current = now
    recordHistory(makeSnapshot())
  }

  const handleNodesChange = useCallback((changes: NodeChange<KxyNode>[]) => {
    const positionChanges = changes.filter((change) => change.type === 'position')
    const structuralChanges = changes.filter((change) => change.type === 'remove')
    const meaningfulPosition = positionChanges.find((change) => change.type === 'position')
    if (structuralChanges.length > 0) recordStructuralHistory()
    if (meaningfulPosition) {
      const dragging = meaningfulPosition.type === 'position' && meaningfulPosition.dragging === true
      if (dragging && !draggingNodeRef.current) {
        recordHistory(makeSnapshot())
        draggingNodeRef.current = true
      }
      if (!dragging && !draggingNodeRef.current) recordHistory(makeSnapshot())
      if (!dragging) draggingNodeRef.current = false
    }
    applyNodesChange(changes)
  }, [applyNodesChange])

  const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
    if (changes.some((change) => change.type === 'remove')) recordStructuralHistory()
    applyEdgesChange(changes)
  }, [applyEdgesChange])

  const addNode = useCallback((kind: NodeKind, position?: { x: number; y: number }, options: { recordHistory?: boolean; loop?: boolean; humanGate?: boolean } = {}): string => {
    if (!workspaceDefaultsReady) {
      showNotice('error', '全局默认设置仍在加载，请稍候再新增节点')
      return ''
    }
    if (options.recordHistory !== false) recordHistory(makeSnapshot())
    const id = `${kind}-${Math.random().toString(36).slice(2, 8)}`
    const location = position || flowInstance?.screenToFlowPosition({ x: 440, y: 330 }) || { x: 420, y: 260 }
    const newNode: KxyNode = { id, type: kind, position: location, data: options.loop && kind === 'blackbox' ? defaultLoopNodeData(defaultAnalyzer, options.humanGate === true) : newNodeData(kind, defaultAnalyzer, outputDefaults) }
    setNodes((current) => [...current, newNode]); setSelectedId(id); setSelectedIds([id])
    return id
  }, [defaultAnalyzer, flowInstance, outputDefaults, setNodes, showNotice, workspaceDefaultsReady])

  const onConnect = useCallback((connection: Connection) => {
    recordHistory(makeSnapshot())
    setEdges((current) => addEdge({ ...connection, id: `edge-${Math.random().toString(36).slice(2, 8)}` }, current))
  }, [setEdges])

  const handleNodeClick = useCallback((event: React.MouseEvent, node: KxyNode) => {
    setSelectedIds((current) => {
      if (event.shiftKey) return current.includes(node.id) ? current.filter((id) => id !== node.id) : [...current, node.id]
      return [node.id]
    })
    setSelectedId(node.id)
  }, [])

  const handleSelectionChange = useCallback(({ nodes: selected }: { nodes: KxyNode[] }) => {
    const ids = selected.map((node) => node.id)
    setSelectedIds(ids)
    if (ids.length === 1) setSelectedId(ids[0])
    if (ids.length === 0) setSelectedId(null)
  }, [])

  const uploadFiles = useCallback(async (selected: FileList | File[], dropPosition?: { x: number; y: number }) => {
    if (selected.length > 0) recordHistory(makeSnapshot())
    const imported: Array<{ file_id: string; name: string; relative_path: string; display_name: string }> = []
    for (const file of Array.from(selected)) {
      try {
        const form = new FormData(); form.append('file', file)
        const asset = await api<FileAsset>('/api/files', { method: 'POST', body: form })
        setFiles((current) => [asset, ...current.filter((item) => item.id !== asset.id)])
        const relativePath = String((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name || asset.display_name).replaceAll('\\', '/')
        imported.push({ file_id: asset.id, name: file.name || asset.display_name, relative_path: relativePath, display_name: relativePath || asset.display_name })
      } catch (error) { showNotice('error', `导入失败：@@ERROR@@`) }
    }
    if (imported.length === 0) return
    const selectedInput = selectedId ? nodes.find((node) => node.id === selectedId && node.type === 'input') : undefined
    const targetId = selectedInput?.id || addNode('input', dropPosition || flowInstance?.screenToFlowPosition({ x: 420, y: 260 }), { recordHistory: false })
    if (!targetId) return
    setNodes((current) => current.map((node) => {
      if (node.id !== targetId) return node
      const existing = Array.isArray(node.data.attachments) ? node.data.attachments : []
      const next = [...existing, ...imported.filter((item) => !existing.some((old) => old.file_id === item.file_id && old.relative_path === item.relative_path))]
      return { ...node, data: { ...node.data, label: node.data.label === '输入' || node.data.label === '文本输入' ? '研究问题与资料' : node.data.label, attachments: next, file_ids: next.map((item) => item.file_id) } }
    }))
    showNotice('ok', imported.length + ' 个附件已加入同一输入卡；原始资料仍按内容哈希保存')
  }, [addNode, flowInstance, nodes, selectedId, setNodes, showNotice])

  const handleDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    const droppedFiles = Array.from(event.dataTransfer.files || [])
    if (droppedFiles.length > 0) {
      const dropPosition = flowInstance?.screenToFlowPosition({ x: event.clientX, y: event.clientY })
      void uploadFiles(droppedFiles, dropPosition)
      return
    }
    const kind = event.dataTransfer.getData('application/x-kxy-node') as NodeKind
    let options: { loop?: boolean; humanGate?: boolean } = {}
    try {
      const parsed = JSON.parse(event.dataTransfer.getData('application/x-kxy-node-options') || '{}') as { loop?: unknown; humanGate?: unknown }
      options = { loop: parsed.loop === true, humanGate: parsed.humanGate === true }
    } catch {
      options = {}
    }
    if (kind && flowInstance) addNode(kind, flowInstance.screenToFlowPosition({ x: event.clientX, y: event.clientY }), options)
  }, [addNode, flowInstance, uploadFiles])

  const enterBlackbox = useCallback((nodeId?: string) => {
    const targetId = nodeId || selectedId
    if (!targetId) return
    const box = nodes.find((node) => node.id === targetId)
    if (!box || box.data.kind !== 'blackbox') return
    const nested = flowFromWorkflow(box.data.workflow || defaultBlackboxWorkflow(box.data.label || '黑盒子'))
    setCanvasStack((current) => [...current, { nodeId: box.id, name: workflowName, workflowId, nodes, edges }])
    setWorkflowName(nested.name || `${workflowName} / ${box.data.label || '黑盒子'}`)
    setNodes(nested.nodes)
    setEdges(nested.edges)
    setSelectedId(null)
    setSelectedIds([])
  }, [edges, nodes, selectedId, setEdges, setNodes, workflowId, workflowName])

  const returnFromBlackbox = useCallback(() => {
    const frame = canvasStack[canvasStack.length - 1]
    if (!frame) return
    const inner: Workflow = { version: 'kxy.workflow.v1', name: workflowName, nodes, edges }
    const parentNodes = frame.nodes.map((node) => node.id === frame.nodeId ? { ...node, data: { ...node.data, workflow: inner } } : node)
    setNodes(parentNodes)
    setEdges(frame.edges)
    setWorkflowName(frame.name)
    setWorkflowId(frame.workflowId)
    setCanvasStack((current) => current.slice(0, -1))
    setSelectedId(frame.nodeId)
    setSelectedIds([frame.nodeId])
    showNotice('ok', '黑盒内部编辑已保存；回到顶层后再保存整个流程')
  }, [canvasStack, edges, nodes, setEdges, setNodes, showNotice, workflowName])

  const packSelection = useCallback(() => {
    const packed = packSelectedNodes(nodes, edges, selectedIds)
    if ('error' in packed) {
      showNotice('error', packed.error)
      return
    }
    recordHistory(makeSnapshot())
    setNodes(packed.nodes)
    setEdges(packed.edges)
    setSelectedId(packed.boxId)
    setSelectedIds([packed.boxId])
    showNotice('ok', '已封装为可进入编辑的黑盒子；内部边、边界 handle 和原节点数据均保留')
  }, [edges, nodes, selectedIds, setEdges, setNodes, showNotice])

  const unpackSelection = useCallback(() => {
    if (selectedIds.length !== 1) {
      showNotice('error', '请只选择一个黑盒子后解包')
      return
    }
    const unpacked = unpackBlackbox(nodes, edges, selectedIds[0])
    if ('error' in unpacked) {
      showNotice('error', unpacked.error)
      return
    }
    recordHistory(makeSnapshot())
    setNodes(unpacked.nodes)
    setEdges(unpacked.edges)
    setSelectedId(null)
    setSelectedIds([])
    showNotice('ok', '黑盒子已解包，外部边界与内部 handle 已恢复')
  }, [edges, nodes, selectedIds, setEdges, setNodes, showNotice])

  const saveWorkflow = useCallback(async () => {
    if (canvasStack.length > 0) {
      returnFromBlackbox()
      return
    }
    try {
      const result = await api<{ id: string; workflow: Workflow }>('/api/workflows', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: workflowId, name: workflowName, workflow: { id: workflowId, name: workflowName, version: 'kxy.workflow.v1', nodes, edges, settings: {} } }) })
      setWorkflowId(result.id); await refreshResources(); showNotice('ok', '流程已保存，运行时会使用独立快照')
    } catch (error) { showNotice('error', `保存失败：${error instanceof Error ? error.message : String(error)}`) }
  }, [canvasStack.length, edges, nodes, refreshResources, returnFromBlackbox, showNotice, workflowId, workflowName])

  const startRun = useCallback(async () => {
    if (canvasStack.length > 0) {
      showNotice('error', '请先返回顶层画布，再运行整个流程')
      return
    }
    try {
      eventSourceRef.current?.close()
      eventSourceRef.current = null
      activeRunIdRef.current = null
      terminalRunIdRef.current = null
      runSyncInFlightRef.current = false
      setRun({ id: 'pending', status: 'pending', nodes: nodes.map((node) => ({ node_id: node.id, status: 'pending' })) })
      const response = await api<{ id: string; status: string }>('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workflow_id: workflowId, workflow: { id: workflowId, name: workflowName, version: 'kxy.workflow.v1', nodes, edges, settings: {} } }) })
      const runId = response.id
      activeRunIdRef.current = runId
      viewedRunIdRef.current = runId
      const initial = await api<Run>(`/api/runs/${runId}`)
      if (activeRunIdRef.current !== runId) return
      setRun(initial)
      if (['succeeded', 'failed', 'cancelled', 'rejected', 'interrupted'].includes(initial.status)) {
        terminalRunIdRef.current = runId
        void refreshRunHistory()
      } else {
        const source = new EventSource(`${API}/api/runs/${runId}/events`)
        eventSourceRef.current = source
        source.onmessage = () => { void syncRun(runId, source) }
        source.onerror = () => { void syncRun(runId, source); source.close() }
      }
      showNotice('ok', '已开始运行，可在下方查看进度和结果')
    } catch (error) { setRun(null); showNotice('error', `无法启动：${error instanceof Error ? error.message : String(error)}`) }
  }, [canvasStack.length, edges, nodes, refreshRunHistory, showNotice, syncRun, workflowId, workflowName])

  const loadTemplate = useCallback((template: Workflow) => {
    recordHistory(makeSnapshot())
    const next = flowFromWorkflow(template); setWorkflowName(next.name); setWorkflowId(next.id); setNodes(next.nodes); setEdges(next.edges); setSelectedId(null); setSelectedIds([]); setCanvasStack([]); showNotice('ok', `${next.name} 已载入，可继续编辑；不会自动运行`)
  }, [setEdges, setNodes, showNotice])

  const importWorkflow = useCallback((file: File) => {
    void file.text().then(async (text) => {
      try {
        const candidate = JSON.parse(text) as Workflow
        const validation = await api<{ ok: boolean; errors?: string[] }>('/api/workflows/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(candidate) })
        if (!validation.ok) throw new Error((validation.errors || ['流程校验失败']).join('；'))
        const next = flowFromWorkflow(candidate)
        clearRunView()
        recordHistory(makeSnapshot())
        setWorkflowName(next.name); setWorkflowId(next.id); setNodes(next.nodes); setEdges(next.edges); setSelectedId(null); setSelectedIds([]); setCanvasStack([]); showNotice('ok', '流程 JSON 已校验并导入；本机缺失技能或资料需重新绑定')
      } catch (error) { showNotice('error', `JSON 无法导入：${error instanceof Error ? error.message : String(error)}`) }
    })
  }, [clearRunView, makeSnapshot, recordHistory, setEdges, setNodes, showNotice])

  const exportWorkflow = useCallback(() => {
    const content = JSON.stringify(stripExportSecrets(composedRootWorkflow), null, 2)
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json' })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${composedRootWorkflow.name || 'kxy-workflow'}.json`; anchor.click(); URL.revokeObjectURL(url)
  }, [composedRootWorkflow])

  const openPortableExport = useCallback(() => {
    const references = portableWorkflowReferences(composedRootWorkflow)
    setPortableExportFileIds([])
    setPortableExportSkillIds([])
    setPortableExportOpen(true)
    setPortableImportOpen(false)
    if (references.fileIds.length === 0 && references.skillIds.length === 0) showNotice('ok', '当前流程没有可选的附件或 Skill；仍可导出无原始内容包')
  }, [composedRootWorkflow, showNotice])

  const exportPortablePackage = useCallback(async () => {
    if (portableImportBusy) return
    setPortableImportBusy(true)
    try {
      const response = await fetch(`${API}/api/workflows/portable/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: composedRootWorkflow, include_file_ids: portableExportFileIds, include_skill_ids: portableExportSkillIds }),
      })
      if (!response.ok) {
        let detail = response.statusText
        try {
          const body = await response.json() as { detail?: unknown }
          detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
        } catch {
          // Keep the HTTP status when the backend did not return JSON.
        }
        throw new Error(detail)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${composedRootWorkflow.name || 'kxy-workflow'}.kxy-workflow.zip`
      anchor.click()
      URL.revokeObjectURL(url)
      setPortableExportOpen(false)
      showNotice('ok', '工作流 ZIP 已导出；未携带未勾选的原始附件或 Skill')
    } catch (error) {
      showNotice('error', `工作流 ZIP 导出失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setPortableImportBusy(false)
    }
  }, [composedRootWorkflow, portableExportFileIds, portableExportSkillIds, portableImportBusy, showNotice])

  const previewPortablePackage = useCallback(async (file: File, preserveBindings = false, allowBusy = false) => {
    if (portableImportBusy && !allowBusy) return
    const previous = preserveBindings ? portableBindings : emptyPortableBindings()
    setPortableImportBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const preview = await api<PortablePreview>('/api/workflows/portable/import/preview', { method: 'POST', body: form })
      const next = emptyPortableBindings()
      preview.resources.attachments.forEach((item) => {
        const previousValue = previous.files[item.source_id]
        const isValidPrevious = previousValue === 'package' ? Boolean(item.included) : item.candidates.some((candidate) => candidate.id === previousValue)
        next.files[item.source_id] = isValidPrevious ? previousValue : item.candidates[0]?.id || (item.included ? 'package' : '')
      })
      preview.resources.skills.forEach((item) => {
        const previousValue = previous.skills[item.source_id]
        const isValidPrevious = previousValue === 'package' ? Boolean(item.included) : item.candidates.some((candidate) => candidate.id === previousValue)
        next.skills[item.source_id] = isValidPrevious ? previousValue : item.candidates[0]?.id || (item.included ? 'package' : '')
      })
      preview.dependencies.models.forEach((item) => {
        const previousValue = previous.models[item.key]
        const selected = previousValue?.model_ref ? item.candidates.find((model) => model.id === previousValue.model_ref) : undefined
        if (selected) {
          const effort = previousValue?.effort && selected.efforts?.includes(previousValue.effort)
            ? previousValue.effort
            : selected.default_effort && selected.efforts?.includes(selected.default_effort) ? selected.default_effort : ''
          next.models[item.key] = { model_ref: selected.id, effort }
        }
      })
      preview.dependencies.mcps.forEach((item) => {
        const previousValue = previous.mcps[item.source_id]
        if (previousValue && item.candidates.some((candidate) => candidate.id === previousValue)) next.mcps[item.source_id] = previousValue
      })
      preview.dependencies.outputs.forEach((item) => {
        const previousValue = previous.outputs[item.key]
        const candidate = item.candidates.find((option) => option.mode === previousValue?.mode && (option.mode === 'default' || option.id === previousValue?.grant_id))
        if (candidate) next.outputs[item.key] = candidate.mode === 'default' ? { mode: 'default' } : { mode: 'grant', grant_id: candidate.id }
      })
      setPortableImportFile(file)
      setPortablePreview(preview)
      setPortableBindings(next)
      setPortableImportOpen(true)
    } catch (error) {
      showNotice('error', `工作流 ZIP 预览失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setPortableImportBusy(false)
    }
  }, [portableBindings, portableImportBusy, showNotice])

  const openPortableImport = useCallback(() => {
    setPortableExportOpen(false)
    setPortableImportOpen(true)
    setPortablePreview(null)
    setPortableBindings(emptyPortableBindings())
    window.setTimeout(() => portableImportInputRef.current?.click(), 0)
  }, [])

  const portableBindingsReady = useMemo(() => {
    if (!portablePreview) return false
    const resourcesReady = portablePreview.resources.attachments.every((item) => {
      const value = portableBindings.files[item.source_id]
      return Boolean(value) && (value !== 'package' || Boolean(item.included))
    }) && portablePreview.resources.skills.every((item) => {
      const value = portableBindings.skills[item.source_id]
      return Boolean(value) && (value !== 'package' || Boolean(item.included))
    })
    const dependenciesReady = portablePreview.dependencies.models.every((item) => Boolean(portableBindings.models[item.key]?.model_ref))
      && portablePreview.dependencies.mcps.every((item) => Boolean(portableBindings.mcps[item.source_id]))
      && portablePreview.dependencies.outputs.every((item) => {
        const value = portableBindings.outputs[item.key]
        return value?.mode === 'default' || (value?.mode === 'grant' && Boolean(value.grant_id))
      })
    return resourcesReady && dependenciesReady
  }, [portableBindings, portablePreview])

  const commitPortablePackage = useCallback(async () => {
    if (portableCommitBusyRef.current || !portablePreview || !portableBindingsReady) return
    portableCommitBusyRef.current = true
    setPortableImportBusy(true)
    try {
      const result = await api<{ ok: boolean; workflow: { id: string; name: string; workflow: Workflow } }>('/api/workflows/portable/import/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          preview_id: portablePreview.preview_id,
          bindings: {
            files: portableBindings.files,
            skills: portableBindings.skills,
            models: portableBindings.models,
            mcps: portableBindings.mcps,
            outputs: portableBindings.outputs,
          },
        }),
      })
      const next = flowFromWorkflow(result.workflow.workflow)
      clearRunView()
      recordHistory(makeSnapshot())
      setWorkflowName(next.name)
      setWorkflowId(result.workflow.id)
      setNodes(next.nodes)
      setEdges(next.edges)
      setSelectedId(null)
      setSelectedIds([])
      setCanvasStack([])
      setPortableImportOpen(false)
      setPortablePreview(null)
      setPortableImportFile(null)
      setPortableBindings(emptyPortableBindings())
      let refreshed = true
      try {
        await refreshResources()
      } catch {
        refreshed = false
      }
      showNotice('ok', refreshed ? '工作流包已创建为新流程并载入；不会自动运行' : '工作流包已导入，但资源列表刷新失败；当前画布已载入')
    } catch (error) {
      showNotice('error', `工作流 ZIP 导入失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      portableCommitBusyRef.current = false
      setPortableImportBusy(false)
    }
  }, [clearRunView, makeSnapshot, portableBindings, portableBindingsReady, portablePreview, recordHistory, refreshResources, setEdges, setNodes, showNotice])

  const refreshPortablePreview = useCallback(async () => {
    if (!portableImportFile) {
      await refreshResources()
      showNotice('ok', '资源列表已刷新；请重新选择 ZIP 以生成预览')
      return
    }
    await previewPortablePackage(portableImportFile, true)
  }, [portableImportFile, previewPortablePackage, refreshResources, showNotice])

  const importPortableMissingFile = useCallback(async (file: File) => {
    const sourceId = portableMissingFileSourceId
    const descriptor = portablePreview?.resources.attachments.find((item) => item.source_id === sourceId)
    if (!sourceId || !descriptor) return
    setPortableImportBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const asset = await api<FileAsset>('/api/files', { method: 'POST', body: form })
      if (asset.sha256 !== descriptor.sha256 || asset.size !== descriptor.size) throw new Error('上传内容与包内声明的 SHA-256/大小不匹配')
      setFiles((current) => [asset, ...current.filter((item) => item.id !== asset.id)])
      if (portableImportFile) await previewPortablePackage(portableImportFile, true, true)
      else await refreshResources()
      setPortableBindings((current) => ({ ...current, files: { ...current.files, [sourceId]: asset.id } }))
      showNotice('ok', `附件 ${asset.display_name} 已导入并重新生成预览`)
    } catch (error) {
      showNotice('error', `缺失附件导入失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setPortableMissingFileSourceId(null)
      setPortableImportBusy(false)
    }
  }, [portableImportFile, portableMissingFileSourceId, portablePreview, previewPortablePackage, refreshResources, showNotice])

  const importPortableMissingSkill = useCallback(async (sourceId: string) => {
    const descriptor = portablePreview?.resources.skills.find((item) => item.source_id === sourceId)
    if (!descriptor) return
    const path = await pickPath('folder')
    if (!path) return
    setPortableImportBusy(true)
    try {
      const skill = await api<Skill>('/api/skills/import-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) })
      if (skill.snapshot_hash !== descriptor.snapshot_hash) throw new Error('导入 Skill 快照与包内声明不匹配')
      setSkills((current) => [skill, ...current.filter((item) => item.id !== skill.id)])
      if (portableImportFile) await previewPortablePackage(portableImportFile, true, true)
      else await refreshResources()
      setPortableBindings((current) => ({ ...current, skills: { ...current.skills, [sourceId]: skill.id } }))
      showNotice('ok', `Skill ${skill.name} 已导入并重新生成预览`)
    } catch (error) {
      showNotice('error', `缺失 Skill 导入失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setPortableImportBusy(false)
    }
  }, [pickPath, portableImportFile, portablePreview, previewPortablePackage, refreshResources, showNotice])

  const authorizePortableOutput = useCallback(async (key: string) => {
    const path = await pickPath('folder')
    if (!path) return
    setPortableImportBusy(true)
    try {
      const grant = await api<{ id: string; canonical_path: string }>('/api/grants', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) })
      setGrants((current) => [grant, ...current.filter((item) => item.id !== grant.id)])
      if (portableImportFile) await previewPortablePackage(portableImportFile, true, true)
      else await refreshResources()
      setPortableBindings((current) => ({ ...current, outputs: { ...current.outputs, [key]: { mode: 'grant', grant_id: grant.id } } }))
      showNotice('ok', `已授权目标目录：${grant.canonical_path}`)
    } catch (error) {
      showNotice('error', `授权目标目录失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setPortableImportBusy(false)
    }
  }, [pickPath, portableImportFile, previewPortablePackage, refreshResources, showNotice])

  const importSkill = useCallback(() => {
    void pickPath('folder').then((path) => {
      if (!path) return
      return api<Skill>('/api/skills/import-path', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) }).then((skill) => { setSkills((current) => [skill, ...current.filter((item) => item.id !== skill.id)]); setSkillHubScan(null); showNotice('ok', `技能 ${skill.name} 已挂载`) })
    }).catch((error) => showNotice('error', `技能导入失败：${error instanceof Error ? error.message : String(error)}`))
  }, [pickPath, showNotice])

  const deleteSkill = useCallback((skillId: string) => {
    void api(`/api/skills/${encodeURIComponent(skillId)}`, { method: 'DELETE' }).then(async () => {
      setSkillHubScan(null)
      removeSkillReferences([skillId])
      try {
        await refreshSkillList()
        showNotice('ok', '技能快照已删除；历史运行快照不受影响')
      } catch (error) {
        setSkills((current) => current.filter((skill) => skill.id !== skillId))
        showNotice('error', `技能记录已删除，但列表刷新失败：${error instanceof Error ? error.message : String(error)}；请重新扫描资源`)
      }
    }).catch(async (error) => {
      let stillExists = true
      try {
        const latest = await refreshSkillList()
        stillExists = latest.some((skill) => skill.id === skillId)
      } catch {
        // Keep the error visible when reconciliation is unavailable.
      }
      if (stillExists) showNotice('error', `技能删除失败：${error instanceof Error ? error.message : String(error)}`)
      else {
        removeSkillReferences([skillId])
        showNotice('error', `技能记录已删除，但快照清理失败：${error instanceof Error ? error.message : String(error)}；请检查暂存目录`)
      }
    })
  }, [refreshSkillList, removeSkillReferences, showNotice])

  const savePreset = useCallback(() => {
    if (!selectedNode) return
    const rawKind = selectedNode.data.kind || selectedNode.type
    if (rawKind === 'subflow_input' || rawKind === 'subflow_output') return
    const kind = rawKind as PresetKind
    const config = presetConfigFromData(selectedNode.data)
    const legacyAnalyzer = kind === 'analyzer'
    const body = legacyAnalyzer
      ? { name: selectedNode.data.label || '未命名分析器', config }
      : { kind, name: selectedNode.data.label || `未命名${presetKindLabels[kind]}`, config }
    const endpoint = legacyAnalyzer ? '/api/analyzers' : '/api/presets'
    void api<ComponentPreset>(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(async (saved) => {
      const mutationRevision = ++analyzerMutationRevisionRef.current
      const preset = { ...saved, kind, source: legacyAnalyzer ? 'analyzer' : 'component' }
      setPresets((current) => [preset, ...current.filter((item) => !(item.id === preset.id && item.source === preset.source))])
      try {
        const latest = await api<ComponentPreset[]>('/api/presets')
        if (analyzerMutationRevisionRef.current === mutationRevision) setPresets(latest)
      } catch {
        // Keep the optimistic record when the follow-up list refresh is unavailable.
      }
      showNotice('ok', `${presetKindLabels[kind]}预设已保存`)
    }).catch((error) => showNotice('error', `预设保存失败：${error instanceof Error ? error.message : String(error)}`))
  }, [selectedNode, showNotice])

  const deletePreset = useCallback((preset: ComponentPreset) => {
    const endpoint = preset.source === 'analyzer' || preset.kind === 'analyzer'
      ? `/api/analyzers/${encodeURIComponent(preset.id)}`
      : `/api/presets/${encodeURIComponent(preset.id)}`
    void api(endpoint, { method: 'DELETE' }).then(() => {
      analyzerMutationRevisionRef.current += 1
      setPresets((current) => current.filter((item) => !(item.id === preset.id && (item.source || 'component') === (preset.source || 'component'))))
      showNotice('ok', `${presetKindLabels[preset.kind]}预设已删除`)
    }).catch((error) => showNotice('error', `预设删除失败：${error instanceof Error ? error.message : String(error)}`))
  }, [showNotice])

  const authorizeGrant = useCallback(() => {
    void pickPath('folder').then((path) => {
      if (!path) return
      return api<{ id: string; canonical_path: string }>('/api/grants', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) }).then((grant) => { setGrants((current) => [grant, ...current]); updateNode({ grant_id: grant.id }); showNotice('ok', '输出授权已保存，可随时撤销') })
    }).catch((error) => showNotice('error', `授权失败：${error instanceof Error ? error.message : String(error)}`))
  }, [pickPath, showNotice, updateNode])

  const storeCredential = useCallback(async (input: CredentialStoreInput): Promise<Credential> => {
    try {
      const credential = await api<Credential>('/api/credentials/store', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
      credentialMutationRevisionRef.current += 1
      setCredentials((current) => [credential, ...current.filter((item) => item.id !== credential.id)])
      showNotice('ok', `${credential.provider} API key 已安全写入 Keychain；仅保留引用`)
      return credential
    } catch (error) {
      showNotice('error', `Keychain 配置失败：${error instanceof Error ? error.message : String(error)}`)
      throw error
    }
  }, [showNotice])

  const updateCredential = useCallback(async (id: string, input: CredentialUpdateInput): Promise<Credential> => {
    try {
      const credential = await api<Credential>(`/api/credentials/${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
      credentialMutationRevisionRef.current += 1
      setCredentials((current) => [credential, ...current.filter((item) => item.id !== credential.id)])
      showNotice('ok', `${credential.name || credential.provider} 服务元数据已更新；Keychain 引用保持受控`)
      return credential
    } catch (error) {
      showNotice('error', `服务更新失败：${error instanceof Error ? error.message : String(error)}`)
      throw error
    }
  }, [showNotice])

  const testCredential = useCallback(async (input: CredentialTestInput): Promise<CredentialTestResult> => {
    return api<CredentialTestResult>('/api/credentials/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
  }, [])

  const revokeGrant = useCallback((id: string) => { void api(`/api/grants/${id}`, { method: 'DELETE' }).then(() => { setGrants((current) => current.map((grant) => grant.id === id ? { ...grant, revoked_at: new Date().toISOString() } : grant)); if (selectedNode?.data.grant_id === id) updateNode({ grant_id: '' }); showNotice('ok', '输出授权已撤销') }).catch((error) => showNotice('error', `撤销失败：${error instanceof Error ? error.message : String(error)}`)) }, [selectedNode, showNotice, updateNode])

  const applyPreset = useCallback((preset: ComponentPreset) => {
    const missing = presetMissingReferences(preset, files, skills, models, grants, credentials, mcps)
    if (missing.length > 0) {
      showNotice('error', `无法应用预设，缺少本机引用：${missing.join('、')}`)
      return
    }
    const kind = preset.kind
    if (kind === 'blackbox') {
      const nested = preset.config.workflow
      if (!nested || typeof nested !== 'object' || !Array.isArray((nested as Workflow).nodes) || !Array.isArray((nested as Workflow).edges)) {
        showNotice('error', '黑盒预设缺少内部工作流，未插入画布')
        return
      }
    }
    if (kind === 'analyzer' && selectedNode?.data.kind === 'analyzer') {
      updateNode(preset.config as Partial<KxyNodeData>)
      showNotice('ok', '分析器预设已应用到当前节点')
      return
    }
    const id = addNode(kind, flowInstance?.screenToFlowPosition({ x: 480, y: 260 }))
    if (!id) return
    const nextData: KxyNodeData = {
      ...defaultNodeData(kind),
      ...preset.config,
      kind,
      label: String(preset.config.label || preset.name),
    }
    if (kind === 'blackbox') {
      const nested = preset.config.workflow
      const sourceWorkflow = flowFromWorkflow(nested as Workflow)
      const remappedWorkflow = remapPresetWorkflow(sourceWorkflow, `${id}__wf`)
      nextData.workflow = remappedWorkflow
      if (preset.config.loop && typeof preset.config.loop === 'object' && !Array.isArray(preset.config.loop)) {
        nextData.loop = remapLoopReferences(preset.config.loop as LoopConfig, sourceWorkflow.nodes, remappedWorkflow.nodes)
      }
    }
    setNodes((current) => current.map((node) => node.id === id ? { ...node, data: nextData } : node))
    showNotice('ok', `${presetKindLabels[kind]}预设已应用；已生成新的节点 ID`)
  }, [addNode, credentials, files, flowInstance, grants, mcps, models, selectedNode, setNodes, showNotice, skills, updateNode])

  const saveAppearance = useCallback(() => { void api<Partial<Appearance>>('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(appearance) }).then((saved) => { const next = { ...DEFAULT_APPEARANCE, ...appearance, ...saved }; setAppearance(next); setBackgroundUrl(next.background_image ? `${API}/api/appearance/background/${encodeURIComponent(next.background_image)}` : ''); showNotice('ok', '默认样式已持久化') }).catch((error) => showNotice('error', `外观保存失败：${error instanceof Error ? error.message : String(error)}`)) }, [appearance, setAppearance, showNotice])
  const resetAppearance = useCallback(() => { setAppearance(DEFAULT_APPEARANCE); setBackgroundUrl('') }, [setAppearance])

  const saveDefaultAnalyzer = useCallback(async (value: DefaultAnalyzerUpdate): Promise<DefaultAnalyzerSetting> => {
    const saved = await api<SettingsResponse>('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ default_analyzer: value }) })
    const next = saved.default_analyzer ? { ...DEFAULT_ANALYZER_SETTING, ...saved.default_analyzer } : DEFAULT_ANALYZER_SETTING
    setDefaultAnalyzer(next)
    return next
  }, [])

  const saveOutputDefaults = useCallback(async (value: OutputDefaults): Promise<OutputDefaults> => {
    const saved = await api<SettingsResponse>('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ output_defaults: value }) })
    const next: OutputDefaults = saved.output_defaults ? { export_formats: [...(saved.output_defaults.export_formats || [])], allowed_file_extensions: [...(saved.output_defaults.allowed_file_extensions || [])], json_mode: saved.output_defaults.json_mode === 'content' ? 'content' : 'full' } : DEFAULT_OUTPUT_DEFAULTS
    setOutputDefaults(next)
    return next
  }, [])

  const setAgentCheckOnSettingsOpenPreference = useCallback(async (value: boolean): Promise<void> => {
    const saved = await api<SettingsResponse>('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent_check_on_settings_open: value }) })
    setAgentCheckOnSettingsOpen(saved.agent_check_on_settings_open === true || String(saved.agent_check_on_settings_open) === 'true')
  }, [])

  const setAutoCheckMountsPreference = useCallback(async (value: boolean): Promise<void> => {
    const saved = await api<SettingsResponse>('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auto_check_mounts: value }) })
    setAutoCheckMounts(saved.auto_check_mounts !== false && String(saved.auto_check_mounts) !== 'false')
  }, [])

  const uploadBackground = useCallback(async (file: File) => {
    try {
      const form = new FormData()
      form.append('file', file)
      const result = await api<{ id: string; url?: string }>('/api/appearance/background', { method: 'POST', body: form })
      const url = result.url?.startsWith('http') ? result.url : `${API}${result.url || `/api/appearance/background/${encodeURIComponent(result.id)}`}`
      setBackgroundUrl(url)
      setAppearance({ background_image: result.id })
      showNotice('ok', '背景图已上传；点击“保存为默认样式”后会持久化')
    } catch (error) {
      showNotice('error', `背景图上传失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [setAppearance, showNotice])

  const clearBackground = useCallback(() => {
    setBackgroundUrl('')
    setAppearance({ background_image: '' })
    showNotice('ok', '背景图已清除；保存后下次打开不再使用')
  }, [setAppearance, showNotice])

  const openSavedWorkflow = useCallback((id: string) => {
    const saved = savedWorkflows.find((item) => item.id === id)
    if (!saved) return
    recordHistory(makeSnapshot())
    const next = flowFromWorkflow(saved.workflow); setWorkflowName(saved.name); setWorkflowId(saved.id); setNodes(next.nodes); setEdges(next.edges); setSelectedId(null); setSelectedIds([]); setCanvasStack([]); showNotice('ok', `${saved.name} 已从本地载入`)
  }, [savedWorkflows, setEdges, setNodes, showNotice])

  const openRunHistory = useCallback((id: string) => {
    viewedRunIdRef.current = id
    void api<Run>(`/api/runs/${id}`).then((next) => { if (viewedRunIdRef.current === id) setRun(next) }).catch((error) => showNotice('error', `运行记录读取失败：${error instanceof Error ? error.message : String(error)}`))
  }, [showNotice])

  const decideApproval = useCallback(async (nodeId: string, decision: 'approve' | 'reject' | 'return', note: string, revisionText?: string | null) => {
    if (!run || run.id === 'pending') return
    const runId = run.id
    try {
      await api<unknown>(`/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(nodeId)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note: note.trim() || undefined, ...(revisionText !== undefined ? { revision_text: revisionText } : {}) }) })
      const next = await api<Run>(`/api/runs/${encodeURIComponent(runId)}`)
      if (viewedRunIdRef.current === runId || activeRunIdRef.current === runId) setRun(next)
      showNotice('ok', decision === 'approve' ? '人工确认已提交，运行将继续' : decision === 'return' ? '已退回循环下一轮；原始审阅结果仍保留在运行记录' : '已终止该人工节点，运行会停止')
    } catch (error) {
      showNotice('error', `人工决定未提交：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [run, showNotice])

  const continueLoop = useCallback(async (loopPath: string, additionalRounds = 1, additionalSeconds = 300) => {
    if (!run) return
    const runId = run.id
    try {
      const next = await api<Run>(`/api/runs/${encodeURIComponent(runId)}/loops/${encodeURIComponent(loopPath)}/continue`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ additional_rounds: additionalRounds, additional_seconds: additionalSeconds }) })
      if (viewedRunIdRef.current === runId || activeRunIdRef.current === runId) setRun(next)
      showNotice('ok', `循环已继续（增加 ${additionalRounds} 轮 / ${additionalSeconds} 秒有界预算）`)
    } catch (error) {
      showNotice('error', `循环继续失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [run, showNotice])

  const stopLoop = useCallback(async (loopPath: string) => {
    if (!run) return
    const runId = run.id
    try {
      const next = await api<Run>(`/api/runs/${encodeURIComponent(runId)}/loops/${encodeURIComponent(loopPath)}/stop`, { method: 'POST' })
      if (viewedRunIdRef.current === runId || activeRunIdRef.current === runId) setRun(next)
      showNotice('ok', '已请求停止循环；未通过结果不会被自动接受')
    } catch (error) {
      showNotice('error', `循环停止失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [run, showNotice])

  useEffect(() => {
    const historyRun = run
    if (!historyRun || historyRun.id === 'pending' || !['pending', 'running', 'waiting'].includes(historyRun.status) || activeRunIdRef.current === historyRun.id) return
    let stopped = false
    let refreshed = false
    const poll = async () => {
      try {
        const next = await api<Run>(`/api/runs/${historyRun.id}`)
        if (stopped || viewedRunIdRef.current !== historyRun.id) return
        setRun(next)
        if (!refreshed && ['succeeded', 'failed', 'cancelled', 'rejected', 'interrupted'].includes(next.status)) {
          refreshed = true
          void refreshRunHistory()
        }
      } catch {
        // Keep polling; a transient local API error should not clear the run view.
      }
    }
    const timer = window.setInterval(() => { void poll() }, 1000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [refreshRunHistory, run])

  const cancelRun = useCallback(() => { if (!run || run.id === 'pending') return; void api(`/api/runs/${run.id}/cancel`, { method: 'POST' }).then(() => showNotice('ok', '已请求取消当前运行')).catch((error) => showNotice('error', `取消失败：${error instanceof Error ? error.message : String(error)}`)) }, [run, showNotice])
  const resumeRun = useCallback(async () => {
    if (!run || !['failed', 'interrupted'].includes(run.status)) return
    const runId = run.id
    try {
      eventSourceRef.current?.close()
      eventSourceRef.current = null
      activeRunIdRef.current = runId
      viewedRunIdRef.current = runId
      terminalRunIdRef.current = null
      runSyncInFlightRef.current = false
      await api<{ id: string; status: string; attempt: number }>(`/api/runs/${encodeURIComponent(runId)}/resume`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const initial = await api<Run>(`/api/runs/${encodeURIComponent(runId)}`)
      if (activeRunIdRef.current !== runId) return
      setRun(initial)
      if (['succeeded', 'failed', 'cancelled', 'rejected', 'interrupted'].includes(initial.status)) {
        terminalRunIdRef.current = runId
        void refreshRunHistory()
      } else {
        const source = new EventSource(`${API}/api/runs/${runId}/events`)
        eventSourceRef.current = source
        source.onmessage = () => { void syncRun(runId, source) }
        source.onerror = () => { void syncRun(runId, source); source.close() }
      }
      showNotice('ok', '已从原始运行快照恢复；成功节点复用，失败节点重新执行')
    } catch (error) {
      showNotice('error', `恢复失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [refreshRunHistory, run, showNotice, syncRun])
  const deleteSelected = useCallback(() => {
    const ids = selectedIds.length ? selectedIds : selectedId ? [selectedId] : []
    if (!ids.length) return
    recordHistory(makeSnapshot())
    const selected = new Set(ids)
    setNodes((current) => current.filter((node) => !selected.has(node.id)))
    setEdges((current) => current.filter((edge) => !selected.has(edge.source) && !selected.has(edge.target)))
    setSelectedId(null)
    setSelectedIds([])
  }, [selectedId, selectedIds, setEdges, setNodes])
  const closeLeftPanel = useCallback(() => { setLeftPanelOpen(false); setMobilePanel(null) }, [])
  const closeRightPanel = useCallback(() => { setRightPanelOpen(false); setMobilePanel(null) }, [])

  const portableExportReferences = useMemo(() => portableWorkflowReferences(composedRootWorkflow), [composedRootWorkflow])
  const appearanceStyle = { ...cssVars, '--kxy-density': appearance.palette === 'mist' ? '0.98' : '1' } as React.CSSProperties
  return (
    <div className={`kxy-app palette-${appearance.palette} font-${appearance.font}`} style={appearanceStyle} onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
      <header className="topbar">
        <div className="brand-lockup">{logoFailed ? <span className="brand-mark">kxy</span> : <img className="brand-logo" src={`${API}/api/branding/logo`} alt="kxy" onError={() => setLogoFailed(true)} />}<span className="brand-divider" /><span className="brand-context">研究画布</span></div>
        <div className="workflow-title"><input aria-label="流程名称" value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} /><select aria-label="打开已保存流程" value="" onChange={(event) => openSavedWorkflow(event.target.value)}><option value="">打开流程</option>{savedWorkflows.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><ChevronDown size={14} /></div>
        <div className="top-actions"><button className="top-button mobile-only" onClick={() => { setLeftPanelOpen(true); setMobilePanel('left') }}><PanelLeft size={15} /></button><button className="top-button desktop-only" onClick={() => setLeftPanelOpen((open) => !open)} title={leftPanelOpen ? '收起组件库' : '打开组件库'}><PanelLeft size={15} />组件库</button><button className="top-button" onClick={() => void saveWorkflow()}><Save size={15} />保存</button><button className="top-button undo-button" onClick={undo} disabled={!historyCount} title={historyCount ? `撤回（剩余 ${historyCount} 步）` : '暂无可撤回的图编辑'} aria-label="撤回"><Undo2 size={15} />撤回{historyCount > 0 && <small>{historyCount}</small>}</button><button className="top-button" onClick={exportWorkflow}><Download size={15} />导出</button><button className="top-button" onClick={() => importInputRef.current?.click()}><Upload size={15} />导入</button><button className="top-button" onClick={openPortableExport} title="导出或导入可迁移工作流包"><PackageOpen size={15} />工作流包</button><button className="top-button" onClick={() => setSettingsOpen(true)} title="全局设置"><Settings2 size={15} />设置</button><button className="run-button" onClick={startRun}><Play size={15} fill="currentColor" />运行流程</button><button className="top-button desktop-only" onClick={() => setRightPanelOpen((open) => !open)} title={rightPanelOpen ? '收起检查器' : '打开检查器'}><PanelRight size={15} />检查器</button><button className="top-button mobile-only" onClick={() => { setRightPanelOpen(true); setMobilePanel('right') }}><PanelRight size={15} /></button></div>
      </header>
      <div className={`workspace-grid ${leftPanelOpen ? '' : 'left-collapsed'} ${rightPanelOpen ? '' : 'right-collapsed'}`}>
          <div className={`panel-wrap left-wrap ${leftPanelOpen ? '' : 'desktop-collapsed'} ${mobilePanel === 'left' ? 'mobile-open' : ''}`}><LibraryPanel canAddNodes={workspaceDefaultsReady} onAdd={(kind, loop, humanGate) => addNode(kind, undefined, { loop, humanGate })} onUpload={() => fileInputRef.current?.click()} onUploadFolder={() => folderInputRef.current?.click()} skills={skills} onImportSkill={importSkill} onDeleteSkill={deleteSkill} onBulkDeleteSkills={bulkDeleteSkills} skillHubScan={skillHubScan} skillHubScanBusy={skillHubScanBusy} skillHubSyncBusy={skillHubSyncBusy} onScanSkillHub={() => void scanSkillHubIndex()} onSyncSkillHub={syncSkillHubIndex} presets={presets} onApplyPreset={applyPreset} onDeletePreset={deletePreset} files={files} models={models} grants={grants} credentials={credentials} mcps={mcps} onClose={closeLeftPanel} /></div>
        <main className="canvas-area">
          {templates.length > 0 && <div className="template-strip canvas-template-strip" aria-label="快速开始"><span>快速开始</span>{templates.map((template) => <button key={template.id} onClick={() => loadTemplate(template)}><LayoutTemplate size={13} />{template.name}</button>)}</div>}
          <div className="canvas-meta"><div><span className="eyebrow">RESEARCH WORKSPACE</span>{canvasStack.length > 0 && <div className="canvas-breadcrumb"><button onClick={returnFromBlackbox}><ArrowLeft size={12} />返回上一级</button><span>研究画布</span>{canvasStack.map((frame) => <span key={`${frame.nodeId}-${frame.name}`}>/ {frame.name}</span>)}<span>/ {workflowName}</span></div>}<h1 title={workflowName}>{workflowName}</h1></div><div className="canvas-meta-actions"><div className="interaction-tools" role="group" aria-label="画布交互模式"><button className={`canvas-tool action-tool ${interactionMode === 'pan' ? 'is-active' : ''}`} aria-pressed={interactionMode === 'pan'} title="移动模式：左键拖动画布；空格或中键也可平移" onClick={() => setInteractionMode('pan')}><Hand size={14} />移动</button><button className={`canvas-tool action-tool ${interactionMode === 'select' ? 'is-active' : ''}`} aria-pressed={interactionMode === 'select'} title="框选模式：左键拖拽框选；Shift 可多选" onClick={() => setInteractionMode('select')}><MousePointer2 size={14} />框选</button></div>{interactionMode === 'select' && selectedIds.length > 0 && <><span className="selection-count">已选 {selectedIds.length}</span><button className="canvas-tool action-tool" title="把当前框选建立为新黑盒子" onClick={packSelection}><Boxes size={14} />新建黑盒</button></>}{selectedIds.length > 0 && selectedIds.length !== 0 && !(interactionMode === 'select' && selectedIds.length > 0) && <button className="canvas-tool action-tool" title="封装选中节点为黑盒子" onClick={packSelection}><Boxes size={14} />封装</button>}{selectedIds.length === 1 && selectedNode?.data.kind === 'blackbox' && <button className="canvas-tool action-tool" title="解包黑盒子并恢复连线" onClick={unpackSelection}><PackageOpen size={14} />解包</button>}<button className="canvas-tool" title="自动适配画布" onClick={() => flowInstance?.fitView({ padding: 0.18, duration: 300 })}><RefreshCw size={15} /></button><button className="canvas-tool" title="外观设置" onClick={() => { setSelectedId(null); setSelectedIds([]); setRightPanelOpen(true); setMobilePanel('right') }}><Palette size={15} /></button><span className="saved-indicator">{canvasStack.length > 0 ? '编辑黑盒内部' : '本地模式'}</span></div></div>
          <div className="flow-frame" ref={flowFrameRef}><ReactFlow<KxyNode, Edge> nodes={displayNodes} edges={edges} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange} onConnect={onConnect} onInit={setFlowInstance} nodeTypes={nodeTypes} onNodeClick={handleNodeClick} onSelectionChange={handleSelectionChange} onNodeDoubleClick={(_, node) => { if (node.type === 'blackbox') enterBlackbox(node.id) }} onPaneClick={() => { setSelectedId(null); setSelectedIds([]) }} fitView fitViewOptions={{ padding: 0.18 }} deleteKeyCode={['Backspace', 'Delete']} selectionOnDrag={interactionMode === 'select'} panOnDrag={interactionMode === 'select' ? [1] : true} panActivationKeyCode="Space" selectionKeyCode={null} multiSelectionKeyCode="Shift" selectionMode={SelectionMode.Partial} proOptions={{ hideAttribution: true }}><Background color="#ded8d0" gap={24} size={1.3} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={(node) => node.data?.kind === 'analyzer' ? '#e6cdb4' : node.data?.kind === 'condition' ? '#ddd5e7' : node.data?.kind === 'blackbox' ? '#dce7f0' : '#d6e0d6'} /><Panel position="bottom-left" className="canvas-hint"><CircleHelp size={13} />{interactionMode === 'select' ? '框选模式 · Shift 多选 · 空格/中键平移 · 双击黑盒编辑' : '移动模式 · 空格/中键平移 · 切换框选后拖拽选择'}</Panel></ReactFlow><CanvasEffects containerRef={flowFrameRef} selectedIds={selectedIds} enabled={appearance.motion_enabled} intensity={appearance.motion_intensity} accent={appearance.accent} />{nodes.length === 0 && <div className="canvas-empty"><Boxes size={28} /><h3>从一份资料开始</h3><p>拖入文件或从左侧添加组件</p></div>}</div>
        </main>
        <div className={`panel-wrap right-wrap ${rightPanelOpen ? '' : 'desktop-collapsed'} ${mobilePanel === 'right' ? 'mobile-open' : ''}`}><InspectorPanel node={selectedNode} run={run} outputPath={selectedNodePath} files={files} skills={skills} grants={grants} agents={agents} models={models} mcps={mcps} conditionSample={conditionSample} filterItems={filterItems} onUpdate={updateNode} onDelete={deleteSelected} onSavePreset={savePreset} onAuthorize={authorizeGrant} onRevoke={revokeGrant} onEnterBlackbox={() => enterBlackbox(selectedId || undefined)} onUnpackBlackbox={unpackSelection} onPreviewSkillMount={previewSkillMount} onCheckSkillDependencies={checkSkillDependencies} onSetSkillDependencies={setSkillDependencies} autoCheckMounts={autoCheckMounts} onUploadAttachment={() => fileInputRef.current?.click()} onUploadAttachmentFolder={() => folderInputRef.current?.click()} onOpenSettings={() => setSettingsOpen(true)} onClose={closeRightPanel} /></div>
      </div>
      <RunPanel run={run} history={runHistory} open={runOpen} onToggle={() => setRunOpen((value) => !value)} onCancel={cancelRun} onResume={() => void resumeRun()} onClear={() => { viewedRunIdRef.current = null; setRun(null) }} onOpenHistory={openRunHistory} onApproval={decideApproval} onLoopContinue={continueLoop} onLoopStop={stopLoop} />
      {notice && <div className={`toast ${notice.type}`}><span>{notice.type === 'ok' ? <Check size={15} /> : <CircleAlert size={15} />}</span>{notice.text}</div>}
      {portableExportOpen && <div className="settings-backdrop portable-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target && !portableImportBusy) setPortableExportOpen(false) }}>
        <section className="settings-modal portable-modal" role="dialog" aria-modal="true" aria-labelledby="portable-export-title">
          <header className="settings-header"><div><span className="eyebrow">PORTABLE WORKFLOW</span><h2 id="portable-export-title">导出可迁移工作流包</h2><p>当前根画布会包含正在编辑的黑盒内部。默认不携带原始附件或 Skill；勾选后会把原始内容写入 ZIP。</p></div><button className="icon-button" onClick={() => setPortableExportOpen(false)} disabled={portableImportBusy} title="关闭"><X size={17} /></button></header>
          <div className="settings-content portable-content">
            <div className="settings-feedback"><CircleAlert size={14} /><span>请确认 ZIP 的分享范围。原始附件与完整 Skill 可能包含私有材料；模型凭据、MCP 凭据和源 output 授权目录不会被导出。</span></div>
            <div className="portable-summary"><strong>{composedRootWorkflow.name}</strong><span>{composedRootWorkflow.nodes.length} 个根节点 · {composedRootWorkflow.edges.length} 条边 · {portableExportReferences.fileIds.length} 个附件引用 · {portableExportReferences.skillIds.length} 个 Skill 引用</span></div>
            <div className="settings-grid portable-export-grid">
              <div className="settings-list-card"><div className="settings-card-heading"><div><span className="field-caption">OPTIONAL ATTACHMENTS</span><strong>原始附件</strong></div><span className="settings-count">默认不选</span></div><p className="helper-copy">只列出当前流程递归引用的附件；勾选后按内容哈希写入 ZIP。</p>{portableExportReferences.fileIds.length === 0 ? <div className="empty-note">没有附件引用。</div> : <div className="portable-check-list">{portableExportReferences.fileIds.map((sourceId) => { const file = files.find((item) => item.id === sourceId); const checked = portableExportFileIds.includes(sourceId); return <label className={`check-field portable-check ${checked ? 'selected' : ''}`} key={sourceId}><input type="checkbox" checked={checked} disabled={portableImportBusy} onChange={(event) => setPortableExportFileIds((current) => event.target.checked ? [...current, sourceId] : current.filter((id) => id !== sourceId))} /><span title={file?.display_name || sourceId}>{file?.display_name || `缺失附件 ${sourceId}`}</span><small>{file ? formatPortableBytes(file.size) : '本机缺失'}</small></label> })}</div>}</div>
              <div className="settings-list-card"><div className="settings-card-heading"><div><span className="field-caption">OPTIONAL SKILLS</span><strong>完整 Skill 快照</strong></div><span className="settings-count">默认不选</span></div><p className="helper-copy">勾选会携带 Skill 文件与安全依赖声明；不勾选只保留绑定所需的快照摘要。</p>{portableExportReferences.skillIds.length === 0 ? <div className="empty-note">没有 Skill 引用。</div> : <div className="portable-check-list">{portableExportReferences.skillIds.map((sourceId) => { const skill = skills.find((item) => item.id === sourceId); const checked = portableExportSkillIds.includes(sourceId); return <label className={`check-field portable-check ${checked ? 'selected' : ''}`} key={sourceId}><input type="checkbox" checked={checked} disabled={portableImportBusy} onChange={(event) => setPortableExportSkillIds((current) => event.target.checked ? [...current, sourceId] : current.filter((id) => id !== sourceId))} /><span title={skill?.name || sourceId}>{skill?.name || `缺失 Skill ${sourceId}`}</span><small>{skill ? '含快照与声明' : '本机缺失'}</small></label> })}</div>}</div>
            </div>
          </div>
          <footer className="settings-actions portable-actions"><button className="outline-button" onClick={openPortableImport} disabled={portableImportBusy}><Upload size={14} />导入 ZIP</button><button className="outline-button" onClick={() => setPortableExportOpen(false)} disabled={portableImportBusy}>取消</button><button className="run-button" onClick={() => void exportPortablePackage()} disabled={portableImportBusy}><Download size={14} className={portableImportBusy ? 'spin' : ''} />{portableImportBusy ? '正在导出…' : '导出工作流 ZIP'}</button></footer>
        </section>
      </div>}
      {portableImportOpen && <div className="settings-backdrop portable-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target && !portableImportBusy) setPortableImportOpen(false) }}>
        <section className="settings-modal portable-modal" role="dialog" aria-modal="true" aria-labelledby="portable-import-title">
          <header className="settings-header"><div><span className="eyebrow">PORTABLE WORKFLOW</span><h2 id="portable-import-title">导入可迁移工作流包</h2><p>先预览依赖和目标绑定，再明确提交为新工作流；预览、取消或失败都不会改动当前画布。</p></div><button className="icon-button" onClick={() => setPortableImportOpen(false)} disabled={portableImportBusy} title="关闭"><X size={17} /></button></header>
          <div className="settings-content portable-content">
            {!portablePreview ? <div className="portable-empty"><PackageOpen size={30} /><h3>选择一个工作流 ZIP</h3><p>不会自动运行，也不会静默跳过缺失的模型、MCP、附件、Skill 或 output 目标。</p><button className="run-button" onClick={() => portableImportInputRef.current?.click()} disabled={portableImportBusy}><Upload size={14} />选择 ZIP</button></div> : <>
              <div className="portable-summary"><strong>{portablePreview.workflow.name}</strong><span>{portablePreview.workflow.nodes} 个节点 · {portablePreview.workflow.edges} 条边 · 预览有效期至 {new Date(portablePreview.expires_at).toLocaleString()}</span><button className="outline-button compact-button" onClick={() => void refreshPortablePreview()} disabled={portableImportBusy}><RefreshCw size={13} className={portableImportBusy ? 'spin' : ''} />刷新资源</button></div>
              <div className="settings-feedback"><CircleCheck size={14} /><span>匹配到的附件/Skill 可预选；模型、MCP、output 初始必须明确选择。提交按钮只创建并载入新流程，不会运行。</span></div>
              <div className="portable-binding-section"><div className="settings-card-heading"><div><span className="field-caption">CONTENT RESOURCES</span><strong>附件与 Skill</strong></div></div>
                {portablePreview.resources.attachments.map((item) => { const value = portableBindings.files[item.source_id] || ''; return <div className="portable-binding-row" key={`file-${item.source_id}`}><div className="portable-binding-copy"><strong title={item.display_name}>{item.display_name}</strong><small>{formatPortableBytes(item.size)} · {item.status === 'matched' ? '本机已匹配' : item.status === 'carried' ? '包内可导入' : '缺失，需要显式补齐'} </small></div><select value={value} disabled={portableImportBusy} onChange={(event) => setPortableBindings((current) => ({ ...current, files: { ...current.files, [item.source_id]: event.target.value } }))}><option value="">选择附件目标</option>{item.candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>复用：{candidate.display_name}</option>)}{item.included && <option value="package">导入包内附件副本</option>}</select>{!item.candidates.length && !item.included && <button className="mini-button" onClick={() => { setPortableMissingFileSourceId(item.source_id); portableMissingFileInputRef.current?.click() }} disabled={portableImportBusy}><Upload size={12} />上传</button>}</div> })}
                {portablePreview.resources.skills.map((item) => { const value = portableBindings.skills[item.source_id] || ''; return <div className="portable-binding-row" key={`skill-${item.source_id}`}><div className="portable-binding-copy"><strong title={item.name}>{item.name}</strong><small>{item.file_count || 0} 个文件 · {formatPortableBytes(item.byte_count || 0)} · {item.declarations && Object.keys(item.declarations).length ? '含依赖声明' : '无依赖声明'}</small></div><select value={value} disabled={portableImportBusy} onChange={(event) => setPortableBindings((current) => ({ ...current, skills: { ...current.skills, [item.source_id]: event.target.value } }))}><option value="">选择 Skill 目标</option>{item.candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>复用：{candidate.name}</option>)}{item.included && <option value="package">导入包内 Skill 快照</option>}</select>{!item.candidates.length && !item.included && <button className="mini-button" onClick={() => void importPortableMissingSkill(item.source_id)} disabled={portableImportBusy}><Upload size={12} />导入 Skill</button>}</div> })}
                {portablePreview.resources.attachments.length === 0 && portablePreview.resources.skills.length === 0 && <div className="empty-note">此包不含附件或 Skill 引用。</div>}
              </div>
              <div className="portable-binding-section"><div className="settings-card-heading"><div><span className="field-caption">RUNTIME DEPENDENCIES</span><strong>模型、MCP 与输出目标</strong></div></div>
                {portablePreview.dependencies.models.map((item) => { const selected = portableBindings.models[item.key]; const model = item.candidates.find((candidate) => candidate.id === selected?.model_ref); const efforts = model?.efforts || []; return <div className="portable-binding-row portable-runtime-row" key={`model-${item.key}`}><div className="portable-binding-copy"><strong>{item.node_name || item.key}</strong><small>源模型：{item.agent_id || 'Agent 默认'} · {item.alias || '无 alias'} · {item.model || item.model_ref || '未指定'}{item.effort ? ` · effort ${item.effort}` : ''}</small></div><select value={selected?.model_ref || ''} disabled={portableImportBusy} onChange={(event) => { const value = event.target.value; setPortableBindings((current) => { const models = { ...current.models }; if (value) { const target = item.candidates.find((candidate) => candidate.id === value); const oldEffort = current.models[item.key]?.effort || ''; const effort = target?.efforts?.includes(oldEffort) ? oldEffort : target?.default_effort && target.efforts?.includes(target.default_effort) ? target.default_effort : ''; models[item.key] = { model_ref: value, effort } } else delete models[item.key]; return { ...current, models } }) }}><option value="">选择目标模型</option>{item.candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.agent_id || candidate.cli_id || 'Agent'} · {candidate.alias || '无 alias'} · {candidate.model || candidate.id}</option>)}</select>{selected?.model_ref && <select value={selected.effort || ''} disabled={portableImportBusy} onChange={(event) => setPortableBindings((current) => ({ ...current, models: { ...current.models, [item.key]: { ...current.models[item.key], model_ref: selected.model_ref, effort: event.target.value } } }))}><option value="">目标默认 effort{model?.default_effort ? `（${model.default_effort}）` : ''}</option>{efforts.map((effort) => <option value={effort} key={effort}>{effort}</option>)}</select>}{!item.candidates.length && <button className="mini-button" onClick={() => setSettingsOpen(true)} disabled={portableImportBusy}><Settings2 size={12} />打开模型设置</button>}</div> })}
                {portablePreview.dependencies.mcps.map((item) => { const value = portableBindings.mcps[item.source_id] || ''; return <div className="portable-binding-row" key={`mcp-${item.source_id}`}><div className="portable-binding-copy"><strong>{item.name || item.source_id}</strong><small>{item.transport || 'MCP'} · 必须明确绑定</small></div><select value={value} disabled={portableImportBusy} onChange={(event) => setPortableBindings((current) => ({ ...current, mcps: { ...current.mcps, [item.source_id]: event.target.value } }))}><option value="">选择目标 MCP</option>{item.candidates.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.name} · {candidate.transport || 'unknown'}</option>)}</select>{!item.candidates.length && <button className="mini-button" onClick={() => setSettingsOpen(true)} disabled={portableImportBusy}><Settings2 size={12} />打开 MCP 设置</button>}</div> })}
                {portablePreview.dependencies.outputs.map((item) => { const selected = portableBindings.outputs[item.key]; const value = selected?.mode === 'grant' ? `grant:${selected.grant_id}` : selected?.mode || ''; return <div className="portable-binding-row" key={`output-${item.key}`}><div className="portable-binding-copy"><strong>{item.node_name || item.key}</strong><small>输出目标必须明确选择；源授权目录不会进入包</small></div><select value={value} disabled={portableImportBusy} onChange={(event) => { const next = event.target.value; setPortableBindings((current) => { const outputs = { ...current.outputs }; if (next === 'default') outputs[item.key] = { mode: 'default' }; else if (next.startsWith('grant:')) outputs[item.key] = { mode: 'grant', grant_id: next.slice(6) }; else delete outputs[item.key]; return { ...current, outputs } }) }}><option value="">选择目标 output</option>{item.candidates.filter((candidate) => candidate.mode === 'default' || candidate.active !== false).map((candidate) => <option value={candidate.mode === 'default' ? 'default' : `grant:${candidate.id}`} key={`${candidate.mode}-${candidate.id}`}>{candidate.mode === 'default' ? candidate.name : candidate.path || candidate.name}</option>)}</select><button className="mini-button" onClick={() => void authorizePortableOutput(item.key)} disabled={portableImportBusy}><FolderOpen size={12} />授权新目录</button></div> })}
                {portablePreview.dependencies.models.length === 0 && portablePreview.dependencies.mcps.length === 0 && portablePreview.dependencies.outputs.length === 0 && <div className="empty-note">此包没有运行时模型、MCP 或 output 依赖。</div>}
              </div>
            </>}
          </div>
          {portablePreview && <footer className="settings-actions portable-actions"><button className="outline-button" onClick={openPortableImport} disabled={portableImportBusy}><Upload size={14} />重新选择 ZIP</button><button className="outline-button" onClick={() => setPortableImportOpen(false)} disabled={portableImportBusy}>取消</button><button className="run-button" onClick={() => void commitPortablePackage()} disabled={portableImportBusy || !portableBindingsReady}><Check size={14} className={portableImportBusy ? 'spin' : ''} />{portableImportBusy ? '正在导入…' : '导入为新工作流'}</button></footer>}
        </section>
      </div>}
      <input ref={fileInputRef} type="file" multiple hidden onChange={(event) => { if (event.target.files) void uploadFiles(event.target.files); event.target.value = '' }} />
      <input ref={folderInputRef} type="file" multiple hidden {...({ webkitdirectory: '', directory: '' } as Record<string, string>)} onChange={(event) => { const files = event.target.files; if (files && files.length > 0) { showNotice('ok', `将导入所选目录内 ${files.length} 个文件`); void uploadFiles(files) } event.target.value = '' }} />
      <input ref={importInputRef} type="file" hidden accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) importWorkflow(file); event.target.value = '' }} />
      <input ref={portableImportInputRef} type="file" hidden accept="application/zip,.zip" onChange={(event) => { const file = event.target.files?.[0]; if (file) void previewPortablePackage(file); event.target.value = '' }} />
      <input ref={portableMissingFileInputRef} type="file" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void importPortableMissingFile(file); event.target.value = '' }} />
      <GlobalSettingsPanel open={settingsOpen} appearance={appearance} agents={agents} models={models} skills={skills} fonts={fonts} backgroundUrl={backgroundUrl} mcps={mcps} credentials={credentials} defaultAnalyzer={defaultAnalyzer} outputDefaults={outputDefaults} agentCheckOnSettingsOpen={agentCheckOnSettingsOpen} autoCheckMounts={autoCheckMounts} onClose={() => setSettingsOpen(false)} onAppearance={(patch) => setAppearance(patch)} onSaveAppearance={saveAppearance} onResetAppearance={resetAppearance} onPickPath={pickPath} onSaveAgent={saveAgent} onDiscoverAgent={discoverAgent} onScanSkills={scanAgentSkills} onImportSkills={importAgentSkills} onStoreCredential={storeCredential} onUpdateCredential={updateCredential} onTestCredential={testCredential} onCreateModel={createModel} onUpdateModel={updateModel} onDeleteModel={deleteModel} onUploadBackground={uploadBackground} onClearBackground={clearBackground} onDiscoverMcps={discoverAgentMcps} onImportMcps={importAgentMcps} onSaveDefaultAnalyzer={saveDefaultAnalyzer} onSaveOutputDefaults={saveOutputDefaults} onSetAgentCheckOnSettingsOpen={setAgentCheckOnSettingsOpenPreference} onSetAutoCheckMounts={setAutoCheckMountsPreference} onProbeAgentRuntime={probeAgentRuntime} onListDependencyChecks={listDependencyChecks} onClearDependencyChecks={clearDependencyChecks} onRefreshAgents={refreshAgents} />
    </div>
  )
}

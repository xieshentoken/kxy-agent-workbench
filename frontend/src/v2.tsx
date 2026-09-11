import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleX,
  Eraser,
  FolderOpen,
  ImagePlus,
  KeyRound,
  LoaderCircle,
  ListFilter,
  MonitorCog,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  ArrowDownUp,
  Trash2,
  X,
} from 'lucide-react'

export type Appearance = {
  palette: 'paper' | 'sage' | 'mist'
  accent: string
  canvas: string
  font: 'system' | 'serif' | 'mono'
  custom_font: string
  text_font: string
  code_font: string
  font_size: number
  code_font_size: number
  background_image: string
  motion_enabled: boolean
  motion_intensity: number
  undo_limit: number
}

export type DefaultAnalyzerSetting = {
  mode: 'cli' | 'model'
  agent_id: string
  prompt?: string
  model_ref?: string
  effort?: string
  model?: string | null
  alias?: string | null
  source?: string | null
  status?: 'available' | 'missing' | string
  reason?: string | null
}

export type DefaultAnalyzerUpdate = {
  mode: 'cli' | 'model'
  agent_id: string
  prompt: string
  model_ref?: string
  effort?: string
}

export type OutputDefaults = {
  export_formats: Array<'markdown' | 'text' | 'json'>
  allowed_file_extensions: string[]
  json_mode: 'content' | 'full'
}

export type AgentId = 'codex' | 'claude' | 'opencode' | 'pi' | 'hermes' | 'workbuddy' | 'deepseek'

export type AgentModel = {
  id: string
  agent_id?: string
  cli_id: string
  model: string
  alias: string
  source: 'native' | 'api' | 'manual' | string
  efforts: string[]
  default_effort?: string
  discovery_source?: string
  credential_id?: string | null
  native_model_ref?: string | null
}

export type AgentModelInput = Omit<AgentModel, 'id' | 'efforts'> & { efforts?: string[] }

export type AgentProfile = {
  id: AgentId | string
  label: string
  executable: string
  skill_roots: string[]
  available: boolean
  version?: string | null
  status: string
  message?: string | null
  models?: AgentModel[]
  efforts?: string[]
  supported_efforts?: string[]
  discovered_at?: string | null
  login?: {
    status: 'verified' | 'not_logged_in' | 'unknown' | 'unsupported' | string
    verified: boolean | null
    checked_at?: string | null
    source?: string
    evidence?: string
    reason?: string
    credential_state?: string
  }
  login_status?: string
  login_checked_at?: string | null
  refresh_error?: string
  runtime?: {
    interpreter?: string | null
    interpreter_version?: string | null
    status?: string
    version?: string | null
    checked_at?: string | null
    message?: string | null
  }
  runtime_interpreter?: string | null
}

export type DependencyCheckItem = {
  name?: string
  kind?: string
  status?: string
  source?: string
  certainty?: string
  verification?: string
  reason?: string | null
}

export type DependencySkillResult = {
  skill_id: string
  status: string
  blocking?: boolean
  runtime?: { status?: string; interpreter?: string | null; version?: string | null; message?: string | null }
  tools?: DependencyCheckItem[]
  env?: DependencyCheckItem[]
  inferred?: DependencyCheckItem[]
  missing?: DependencyCheckItem[]
  needs_manual?: DependencyCheckItem[]
  declared_dependencies?: Record<string, unknown>
  trusted_tool_checks?: DependencyCheckItem[]
  message?: string
  source?: string
  checked_at?: string | null
  expires_at?: string | null
  duration_ms?: number
  cache_hit?: boolean
  invalidation_reason?: string | null
}

export type DependencyCheckResponse = {
  agent_id: string
  skills: DependencySkillResult[]
  status: string
  checked_at?: string
  force?: boolean
  cache?: { hits?: number; misses?: number; ttl_success_seconds?: number; ttl_pending_seconds?: number }
}

export type DependencyCacheRecord = DependencySkillResult & {
  cache_key?: string
  agent_id?: string
  checker_version?: string
}

export type Skill = {
  id: string
  name: string
  description: string
  snapshot_hash: string
  metadata: Record<string, unknown>
}

export type LocalFont = { family: string; monospace: boolean }

export type McpRecord = {
  id: string
  name: string
  transport?: string
  source_agent?: string
  supported?: boolean
  reason?: string
}

export type McpCandidate = McpRecord & { source_agent: string }

export type SkillCandidate = {
  id?: string
  name: string
  description?: string
  path: string
  source?: string
  compatible?: string
  dependencies?: string
  modified_at?: string
}

export type Credential = {
  id: string
  name?: string
  provider: string
  api_format?: 'openai-chat-completions' | 'openai-responses' | 'anthropic-messages' | 'google-generative-ai' | string
  models?: Array<{ id: string; alias: string }>
  credential_ref: string
  endpoint?: string
  env_name: string
  configured: boolean
}

export type CredentialStoreInput = {
  name?: string
  provider: string
  api_format?: string
  api_key: string
  endpoint: string
  env_name: string
  models?: Array<{ id: string; alias: string }>
}

export type CredentialUpdateInput = Partial<Omit<CredentialStoreInput, 'api_key'>> & { api_key?: string }

export type CredentialTestInput = {
  provider?: string
  api_format?: string
  env_name?: string
  endpoint?: string
  api_key?: string
  credential_id?: string
}

export type CredentialTestResult = {
  ok: boolean
  status: string
  message: string
  latency_ms: number
  provider: string
  endpoint: string
  api_format?: string
  models?: Array<{ id: string; alias: string }>
  model_count?: number
}

export const DEFAULT_APPEARANCE: Appearance = {
  palette: 'paper',
  accent: '#987a5d',
  canvas: '#faf8f5',
  font: 'system',
  custom_font: '',
  text_font: '',
  code_font: '',
  font_size: 14,
  code_font_size: 13,
  background_image: '',
  motion_enabled: true,
  motion_intensity: 30,
  undo_limit: 5,
}

export const DEFAULT_ANALYZER_PROMPT = '请基于输入资料给出可核查、带边界的分析。\n\n如需读取本次运行资料，请打开 input-context.json；输入文件副本位于 inputs/。若已选择 Skill，请读取 skill-manifest.json 中列出的快照；生成文件请写入 outputs/。'

export const DEFAULT_ANALYZER_SETTING: DefaultAnalyzerSetting = {
  mode: 'cli',
  agent_id: 'codex',
  prompt: DEFAULT_ANALYZER_PROMPT,
  status: 'available',
  reason: '使用该 Agent 的默认模型；新建分析器不会固定模型。',
}

export const DEFAULT_OUTPUT_DEFAULTS: OutputDefaults = {
  export_formats: [],
  allowed_file_extensions: [],
  json_mode: 'full',
}

const AGENT_DEFAULTS: Array<{ id: AgentId; label: string }> = [
  { id: 'codex', label: 'Codex' },
  { id: 'claude', label: 'Claude Code' },
  { id: 'opencode', label: 'OpenCode' },
  { id: 'pi', label: 'pi' },
  { id: 'hermes', label: 'Hermes' },
  { id: 'workbuddy', label: 'WorkBuddy' },
  { id: 'deepseek', label: 'DeepSeek Harness' },
]

export function mergeAgentProfiles(input: AgentProfile[]): AgentProfile[] {
  const byId = new Map(input.map((agent) => [agent.id, agent]))
  return AGENT_DEFAULTS.map(({ id, label }) => {
    const profile = byId.get(id)
    const efforts = Array.isArray(profile?.efforts) ? profile.efforts : Array.isArray(profile?.supported_efforts) ? profile.supported_efforts : []
    return {
      id,
      executable: '',
      skill_roots: [],
      available: false,
      status: 'unavailable',
      message: '尚未配置或后端未发现该 Agent',
      ...profile,
      efforts,
      label: profile?.label || label,
    }
  })
}

function sourceLabel(source: string, nativeModelRef?: string | null, credentialId?: string | null, isNewLogin = false): string {
  if (nativeModelRef) return '登录态（本机 CLI）'
  if (source === 'native') return '原生目录'
  if (source === 'api') return 'API'
  if (credentialId) return '历史 API 配置'
  return isNewLogin ? '登录态（本机 CLI）' : 'CLI 登录（旧配置）'
}

function sourceDescription(source: string, nativeModelRef?: string | null, credentialId?: string | null, isNewLogin = false): string {
  if (nativeModelRef) return '登录态：模型来自当前 Agent 的本机 CLI 目录；alias 与默认 effort 可保存为独立配置，不写入 API 凭据。'
  if (source === 'native') return '原生目录：来自 CLI discovery；只读目录，不代表账号已登录或模型有权限。'
  if (source === 'api') return 'API：绑定 Keychain credential；运行仍使用所选 CLI，不是独立 HTTP 推理通道。'
  if (credentialId) return '历史 API 配置：保留旧版手填模型与凭据引用；新配置请使用 API 或本机 CLI 登录态。'
  return isNewLogin ? '登录态：先从本机 CLI 发现的模型目录中选择，再保存 alias 与默认 effort。' : 'CLI 登录（旧配置）：旧版手填模型仍可读取，但不会自动替换或伪造新的目录记录。'
}

function providerDefaultEndpoint(provider: string): string {
  if (provider === 'anthropic') return 'https://api.anthropic.com/v1'
  if (provider === 'google') return 'https://generativelanguage.googleapis.com/v1beta'
  if (provider === 'custom') return ''
  return 'https://api.openai.com/v1'
}

function providerDefaultFormat(provider: string): string {
  if (provider === 'anthropic') return 'anthropic-messages'
  if (provider === 'google') return 'google-generative-ai'
  if (provider === 'custom') return 'openai-chat-completions'
  return 'openai-responses'
}

function providerDefaultEnv(provider: string): string {
  if (provider === 'anthropic') return 'ANTHROPIC_API_KEY'
  if (provider === 'google') return 'GEMINI_API_KEY'
  return 'OPENAI_API_KEY'
}

function apiFormatDefaultEnv(apiFormat: string): string {
  if (apiFormat === 'anthropic-messages') return 'ANTHROPIC_API_KEY'
  if (apiFormat === 'google-generative-ai') return 'GEMINI_API_KEY'
  return 'OPENAI_API_KEY'
}

const VERIFIED_AGENT_API_FORMATS: Record<string, string[]> = {
  codex: ['openai-responses'],
  claude: ['anthropic-messages'],
  pi: ['openai-chat-completions', 'openai-responses', 'anthropic-messages', 'google-generative-ai'],
  opencode: ['openai-chat-completions', 'openai-responses', 'anthropic-messages'],
}

function credentialApiFormat(credential: Credential): string {
  if (credential.api_format) return credential.api_format
  if (credential.env_name === 'GEMINI_API_KEY' || credential.provider === 'google') return 'google-generative-ai'
  if (credential.env_name === 'ANTHROPIC_API_KEY' || credential.provider === 'anthropic') return 'anthropic-messages'
  return 'openai-responses'
}

function serviceCompatible(agentId: string, credential: Credential): boolean {
  return (VERIFIED_AGENT_API_FORMATS[agentId] || []).includes(credentialApiFormat(credential))
}

function agentApiCompatibilityHint(agentId: string): string {
  const formats = VERIFIED_AGENT_API_FORMATS[agentId] || []
  if (!formats.length) return '该 Agent 当前没有已验证的服务映射；不支持的组合会被拒绝。'
  return `当前 Agent 已验证：${formats.join('、')}；其他服务会被禁用。`
}

const SERVICE_PRESETS = [
  { id: 'custom', label: 'Custom', provider: 'custom', api_format: 'openai-chat-completions', endpoint: '', env_name: 'OPENAI_API_KEY' },
  { id: 'openai', label: 'OpenAI', provider: 'openai', api_format: 'openai-responses', endpoint: 'https://api.openai.com/v1', env_name: 'OPENAI_API_KEY' },
  { id: 'anthropic', label: 'Anthropic', provider: 'anthropic', api_format: 'anthropic-messages', endpoint: 'https://api.anthropic.com/v1', env_name: 'ANTHROPIC_API_KEY' },
  { id: 'google', label: 'Google', provider: 'google', api_format: 'google-generative-ai', endpoint: 'https://generativelanguage.googleapis.com/v1beta', env_name: 'GEMINI_API_KEY' },
  { id: 'openrouter', label: 'OpenRouter', provider: 'custom', api_format: 'openai-chat-completions', endpoint: 'https://openrouter.ai/api/v1', env_name: 'OPENAI_API_KEY' },
] as const

type ServiceDraft = {
  name: string
  provider: string
  api_format: string
  endpoint: string
  env_name: string
  models: Array<{ id: string; alias: string }>
}

function normalizeCandidate(value: unknown, index: number): SkillCandidate | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const path = [item.path, item.root_path, item.parent_path, item.skill_path].find((part): part is string => typeof part === 'string' && Boolean(part.trim()))
  if (!path) return null
  const name = [item.name, item.skill_name, item.title].find((part): part is string => typeof part === 'string' && Boolean(part.trim())) || path.split('/').filter(Boolean).pop() || `技能 ${index + 1}`
  return {
    id: typeof item.id === 'string' ? item.id : undefined,
    name,
    description: typeof item.description === 'string' ? item.description : '',
    path,
    source: typeof item.source === 'string' ? item.source : '',
    compatible: typeof item.compatible === 'string' ? item.compatible : '',
    dependencies: typeof item.dependencies === 'string' ? item.dependencies : '',
    modified_at: typeof item.modified_at === 'string' ? item.modified_at : typeof item.modifiedAt === 'string' ? item.modifiedAt : '',
  }
}

type GlobalSettingsProps = {
  open: boolean
  appearance: Appearance
  agents: AgentProfile[]
  models: AgentModel[]
  skills: Skill[]
  fonts: LocalFont[]
  backgroundUrl: string
  mcps: McpRecord[]
  credentials: Credential[]
  defaultAnalyzer: DefaultAnalyzerSetting
  outputDefaults: OutputDefaults
  agentCheckOnSettingsOpen: boolean
  autoCheckMounts: boolean
  onClose: () => void
  onAppearance: (patch: Partial<Appearance>) => void
  onSaveAppearance: () => void
  onResetAppearance: () => void
  onPickPath: (kind: 'file' | 'folder') => Promise<string | null>
  onSaveAgent: (agent: AgentProfile) => Promise<void>
  onDiscoverAgent: (id: string) => Promise<AgentProfile | null>
  onScanSkills: (id: string) => Promise<unknown[]>
  onImportSkills: (id: string, paths: string[]) => Promise<{ imported?: Skill[]; errors?: string[] }>
  onStoreCredential: (input: CredentialStoreInput) => Promise<Credential>
  onUpdateCredential: (id: string, input: CredentialUpdateInput) => Promise<Credential>
  onTestCredential: (input: CredentialTestInput) => Promise<CredentialTestResult>
  onCreateModel: (payload: AgentModelInput) => Promise<AgentModel>
  onUpdateModel: (id: string, payload: Partial<AgentModel>) => Promise<AgentModel>
  onDeleteModel: (id: string) => Promise<void>
  onUploadBackground: (file: File) => Promise<void>
  onClearBackground: () => void
  onDiscoverMcps: (id: string) => Promise<McpCandidate[]>
  onImportMcps: (id: string, ids: string[]) => Promise<{ imported?: McpRecord[]; errors?: string[] }>
  onSaveDefaultAnalyzer: (value: DefaultAnalyzerUpdate) => Promise<DefaultAnalyzerSetting>
  onSaveOutputDefaults: (value: OutputDefaults) => Promise<OutputDefaults>
  onSetAgentCheckOnSettingsOpen: (value: boolean) => Promise<void>
  onSetAutoCheckMounts: (value: boolean) => Promise<void>
  onProbeAgentRuntime: (id: string, interpreter?: string) => Promise<AgentProfile>
  onListDependencyChecks: (skillId?: string) => Promise<DependencyCacheRecord[]>
  onClearDependencyChecks: (skillId?: string) => Promise<number>
  onRefreshAgents: () => Promise<{ succeeded: number; failed: number }>
}

export function GlobalSettingsPanel({
  open,
  appearance,
  agents,
  models,
  skills,
  fonts,
  backgroundUrl,
  mcps,
  credentials,
  onClose,
  onAppearance,
  onSaveAppearance,
  onResetAppearance,
  onPickPath,
  onSaveAgent,
  onDiscoverAgent,
  onScanSkills,
  onImportSkills,
  onStoreCredential,
  onUpdateCredential,
  onTestCredential,
  onCreateModel,
  onUpdateModel,
  onDeleteModel,
  onUploadBackground,
  onClearBackground,
  onDiscoverMcps,
  onImportMcps,
  defaultAnalyzer,
  outputDefaults,
  agentCheckOnSettingsOpen,
  autoCheckMounts,
  onSaveDefaultAnalyzer,
  onSaveOutputDefaults,
  onSetAgentCheckOnSettingsOpen,
  onSetAutoCheckMounts,
  onProbeAgentRuntime,
  onListDependencyChecks,
  onClearDependencyChecks,
  onRefreshAgents,
}: GlobalSettingsProps) {
  const [tab, setTab] = useState<'agents' | 'services' | 'models' | 'defaults' | 'appearance'>('agents')
  const [selectedAgentId, setSelectedAgentId] = useState('codex')
  const [agentDrafts, setAgentDrafts] = useState<Record<string, AgentProfile>>({})
  const [scanned, setScanned] = useState<SkillCandidate[]>([])
  const [selectedScanned, setSelectedScanned] = useState<string[]>([])
  const [skillQuery, setSkillQuery] = useState('')
  const [skillSort, setSkillSort] = useState<'name' | 'modified_at'>('name')
  const [skillSortDirection, setSkillSortDirection] = useState<'asc' | 'desc'>('asc')
  const [mcpCandidates, setMcpCandidates] = useState<McpCandidate[]>([])
  const [selectedMcps, setSelectedMcps] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [editingModelId, setEditingModelId] = useState<string | null>(null)
  const [modelDraft, setModelDraft] = useState<Omit<AgentModel, 'id'>>({ cli_id: 'codex', model: '', alias: '', source: 'manual', efforts: [], default_effort: '', discovery_source: 'manual', credential_id: null, native_model_ref: null })
  const [editingServiceId, setEditingServiceId] = useState<string | null>(null)
  const [serviceDraft, setServiceDraft] = useState<ServiceDraft>({ name: '', provider: 'openai', api_format: 'openai-responses', endpoint: providerDefaultEndpoint('openai'), env_name: 'OPENAI_API_KEY', models: [] })
  const [serviceKey, setServiceKey] = useState('')
  const [serviceQuery, setServiceQuery] = useState('')
  const [serviceModelInput, setServiceModelInput] = useState('')
  const [serviceCatalog, setServiceCatalog] = useState<Array<{ id: string; alias: string }>>([])
  const [serviceTest, setServiceTest] = useState<CredentialTestResult | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [dependencyCache, setDependencyCache] = useState<DependencyCacheRecord[]>([])
  const [defaultMode, setDefaultMode] = useState<'cli' | 'model'>(defaultAnalyzer.mode === 'model' ? 'model' : 'cli')
  const [defaultAgentId, setDefaultAgentId] = useState(defaultAnalyzer.agent_id || 'codex')
  const [defaultModelRef, setDefaultModelRef] = useState(defaultAnalyzer.model_ref || '')
  const [defaultEffort, setDefaultEffort] = useState(defaultAnalyzer.effort || '')
  const [defaultPrompt, setDefaultPrompt] = useState(defaultAnalyzer.prompt ?? DEFAULT_ANALYZER_PROMPT)
  const [outputDraft, setOutputDraft] = useState<OutputDefaults>({
    export_formats: [...(outputDefaults.export_formats || [])],
    allowed_file_extensions: [...(outputDefaults.allowed_file_extensions || [])],
    json_mode: outputDefaults.json_mode || 'full',
  })
  const backgroundInputRef = useRef<HTMLInputElement>(null)
  const selectedAgentRef = useRef('codex')
  const discoverSequenceRef = useRef(0)

  const generatedExtensions = ['.txt', '.md', '.json', '.csv', '.pdf', '.docx', '.xlsx', '.pptx', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.html', '.mp4', '.avi', '.zip']

  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId) || agents[0]
  const currentAgent = selectedAgent ? { ...selectedAgent, ...(agentDrafts[selectedAgent.id] ? { executable: agentDrafts[selectedAgent.id].executable, skill_roots: agentDrafts[selectedAgent.id].skill_roots, runtime_interpreter: agentDrafts[selectedAgent.id].runtime_interpreter } : {}) } : null
  const editingModelIsNative = Boolean(editingModelId && models.find((model) => model.id === editingModelId)?.source === 'native')
  const editingModelIsLogin = Boolean(editingModelId && models.find((model) => model.id === editingModelId)?.native_model_ref)
  const modelDraftIsLogin = modelDraft.source === 'manual' && (!editingModelId || Boolean(modelDraft.native_model_ref))
  const selectedAgentModels = useMemo(() => models.filter((model) => (model.agent_id || model.cli_id) === selectedAgentId), [models, selectedAgentId])
  const nativeCatalogModels = useMemo(() => selectedAgentModels.filter((model) => model.source === 'native' && !model.native_model_ref), [selectedAgentModels])
  const configuredModels = useMemo(() => selectedAgentModels.filter((model) => model.source !== 'native' || Boolean(model.native_model_ref)), [selectedAgentModels])
  const knownCredentials = useMemo(() => credentials.filter((credential) => credential.configured), [credentials])
  const serviceList = credentials
  const servicePresetValue = SERVICE_PRESETS.find((preset) => preset.provider === serviceDraft.provider && preset.api_format === serviceDraft.api_format && preset.endpoint === serviceDraft.endpoint)?.id || 'custom'
  const selectedModelService = knownCredentials.find((credential) => credential.id === modelDraft.credential_id)
  const filteredServiceModels = useMemo(() => {
    const query = serviceQuery.trim().toLocaleLowerCase()
    return serviceCatalog.filter((model) => !query || `${model.id} ${model.alias}`.toLocaleLowerCase().includes(query))
  }, [serviceCatalog, serviceQuery])
  const filteredScanned = useMemo(() => {
    const query = skillQuery.trim().toLocaleLowerCase()
    const next = scanned.filter((candidate) => !query || candidate.name.toLocaleLowerCase().includes(query))
    return next.sort((left, right) => {
      const leftValue = skillSort === 'name' ? left.name.toLocaleLowerCase() : left.modified_at || ''
      const rightValue = skillSort === 'name' ? right.name.toLocaleLowerCase() : right.modified_at || ''
      const result = leftValue.localeCompare(rightValue, 'zh-Hans')
      return skillSortDirection === 'asc' ? result : -result
    })
  }, [scanned, skillQuery, skillSort, skillSortDirection])

  useEffect(() => {
    if (!open) return
    setFeedback(null)
  }, [open, tab])

  useEffect(() => {
    if (!open || !agentCheckOnSettingsOpen) return
    let active = true
    setBusy('discover-all')
    void onRefreshAgents().then((result) => {
      if (active) setFeedback(`已检查 ${result.succeeded} 个 Agent${result.failed ? `；${result.failed} 个失败` : ''}。模型目录与登录态已分开判断。`)
    }).catch((error) => {
      if (active) setFeedback(`批量检查失败：${error instanceof Error ? error.message : String(error)}`)
    }).finally(() => {
      if (active) setBusy(null)
    })
    return () => { active = false }
  }, [open, agentCheckOnSettingsOpen, onRefreshAgents])

  useEffect(() => {
    if (!open) return
    setDefaultMode(defaultAnalyzer.mode === 'model' ? 'model' : 'cli')
    setDefaultAgentId(defaultAnalyzer.agent_id || 'codex')
    setDefaultModelRef(defaultAnalyzer.model_ref || '')
    setDefaultEffort(defaultAnalyzer.effort || '')
    setDefaultPrompt(defaultAnalyzer.prompt ?? DEFAULT_ANALYZER_PROMPT)
  }, [open, defaultAnalyzer.mode, defaultAnalyzer.agent_id, defaultAnalyzer.model_ref, defaultAnalyzer.effort, defaultAnalyzer.prompt])

  useEffect(() => {
    if (!open) return
    setOutputDraft({
      export_formats: [...(outputDefaults.export_formats || [])],
      allowed_file_extensions: [...(outputDefaults.allowed_file_extensions || [])],
      json_mode: outputDefaults.json_mode || 'full',
    })
  }, [open, outputDefaults.export_formats, outputDefaults.allowed_file_extensions, outputDefaults.json_mode])

  if (!open) return null

  const updateAgentDraft = (patch: Partial<AgentProfile>) => {
    if (!currentAgent) return
    setAgentDrafts((current) => ({ ...current, [currentAgent.id]: { ...currentAgent, ...patch } }))
  }

  const selectAgent = (id: string) => {
    selectedAgentRef.current = id
    setSelectedAgentId(id)
    setEditingModelId(null)
    setModelDraft({ cli_id: id, model: '', alias: '', source: 'manual', efforts: [], default_effort: '', discovery_source: 'manual', credential_id: null, native_model_ref: null })
    setScanned([])
    setSelectedScanned([])
    setFeedback(null)
  }

  const discover = async (id: string) => {
    const sequence = discoverSequenceRef.current + 1
    discoverSequenceRef.current = sequence
    setBusy(`discover:${id}`)
    try {
      const profile = await onDiscoverAgent(id)
      if (sequence === discoverSequenceRef.current && selectedAgentRef.current === id) setFeedback(profile?.refresh_error ? `检查完成但有部分失败：${profile.refresh_error}` : '已刷新该 Agent 的版本、模型与 effort；发现结果不代表已登录或可计费。')
    } catch (error) {
      if (sequence === discoverSequenceRef.current && selectedAgentRef.current === id) setFeedback(`发现失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (sequence === discoverSequenceRef.current) setBusy(null)
    }
  }

  const refreshAllAgents = async () => {
    setBusy('discover-all')
    try {
      const result = await onRefreshAgents()
      setFeedback(`已检查 ${result.succeeded} 个 Agent${result.failed ? `；${result.failed} 个失败` : ''}。未执行登录、登出、浏览器授权或推理。`)
    } catch (error) {
      setFeedback(`批量检查失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const probeRuntime = async () => {
    if (!currentAgent) return
    setBusy(`runtime:${currentAgent.id}`)
    try {
      const profile = await onProbeAgentRuntime(currentAgent.id, currentAgent.runtime_interpreter || undefined)
      updateAgentDraft({
        runtime_interpreter: profile.runtime_interpreter ?? currentAgent.runtime_interpreter,
        runtime: profile.runtime,
      })
      setFeedback(profile.runtime?.status === 'READY'
        ? `已验证 ${profile.label} runtime：${profile.runtime?.version || 'Agent 可启动'}。保存 Agent 后固定此绑定。`
        : `${profile.label} runtime 未通过：${profile.runtime?.message || profile.status || '请检查解释器路径。'}`)
    } catch (error) {
      setFeedback(`runtime 检查失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const loadDependencyCache = async () => {
    setBusy('dependency-cache')
    try {
      setDependencyCache(await onListDependencyChecks())
      setFeedback('已读取本地依赖检查缓存；缓存只包含状态、时间和无密钥指纹。')
    } catch (error) {
      setFeedback(`依赖缓存读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const clearDependencyCache = async () => {
    setBusy('dependency-cache-clear')
    try {
      const cleared = await onClearDependencyChecks()
      setDependencyCache([])
      setFeedback(`已清理 ${cleared} 条依赖检查缓存；不会删除 Skill 快照或修改挂载。`)
    } catch (error) {
      setFeedback(`依赖缓存清理失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const saveDefaultAnalyzer = async () => {
    if (defaultMode === 'model' && !defaultModelRef) {
      setFeedback('请选择一个已保存的模型配置；删除或不可用的绑定不会自动换成其他模型。')
      return
    }
    setBusy('default-analyzer-save')
    try {
      const saved = await onSaveDefaultAnalyzer({
        mode: defaultMode,
        agent_id: defaultAgentId,
        prompt: defaultPrompt,
        ...(defaultMode === 'model' ? { model_ref: defaultModelRef, effort: defaultEffort } : {}),
      })
      setFeedback(saved.status === 'missing' ? `默认模型已保存，但当前不可用：${saved.reason || '请重新绑定或清除固定模型。'}` : '新建分析器默认值已保存；已有节点、导入流程和显式预设不变。')
    } catch (error) {
      setFeedback(`默认分析器保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const clearDefaultAnalyzer = async () => {
    setDefaultMode('cli')
    setDefaultModelRef('')
    setDefaultEffort('')
    setBusy('default-analyzer-save')
    try {
      await onSaveDefaultAnalyzer({ mode: 'cli', agent_id: defaultAgentId, prompt: defaultPrompt })
      setFeedback('已清除固定模型；新建分析器回退到所选 Agent 的默认模型。')
    } catch (error) {
      setFeedback(`清除默认模型失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const saveOutputDefaults = async () => {
    setBusy('output-defaults-save')
    try {
      await onSaveOutputDefaults(outputDraft)
      setFeedback('输出默认值已保存；只影响之后新建的输出容器，不改已有节点或历史运行。')
    } catch (error) {
      setFeedback(`输出默认值保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const selectedDefaultModel = models.find((model) => model.id === defaultModelRef)
  const defaultEffortOptions = selectedDefaultModel?.efforts || []
  const defaultSummary = defaultAnalyzer.mode === 'model'
    ? `${defaultAnalyzer.alias || defaultAnalyzer.model || '固定模型'} · ${defaultAnalyzer.agent_id}`
    : `${defaultAnalyzer.agent_id || 'codex'} · Agent 默认模型`

  const saveAgent = async () => {
    if (!currentAgent) return
    setBusy(`save:${currentAgent.id}`)
    try {
      await onSaveAgent(currentAgent)
      setAgentDrafts((current) => {
        const next = { ...current }
        delete next[currentAgent.id]
        return next
      })
      setFeedback('Agent 配置已保存；未修改全局 CLI 配置。')
    } catch (error) {
      setFeedback(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const chooseExecutable = async () => {
    if (!currentAgent) return
    const path = await onPickPath('file')
    if (path) updateAgentDraft({ executable: path })
  }

  const addSkillRoot = async () => {
    if (!currentAgent) return
    const path = await onPickPath('folder')
    if (path && !currentAgent.skill_roots.includes(path)) updateAgentDraft({ skill_roots: [...currentAgent.skill_roots, path] })
  }

  const scanSkills = async () => {
    if (!currentAgent) return
    setBusy(`scan:${currentAgent.id}`)
    try {
      const values = await onScanSkills(currentAgent.id)
      const candidates = values.map(normalizeCandidate).filter((item): item is SkillCandidate => Boolean(item))
      setScanned(candidates)
      setSelectedScanned([])
      setFeedback(candidates.length ? `发现 ${candidates.length} 个可选 Skill；勾选后再导入快照。` : '所选技能目录中没有发现可导入的 SKILL.md。')
    } catch (error) {
      setFeedback(`扫描失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const importSkills = async () => {
    if (!currentAgent || selectedScanned.length === 0) return
    setBusy(`import:${currentAgent.id}`)
    try {
      const result = await onImportSkills(currentAgent.id, selectedScanned)
      setFeedback(`${result.imported?.length || 0} 个 Skill 已导入${result.errors?.length ? `；${result.errors.length} 个被拒绝` : ''}。`)
      setSelectedScanned([])
      setScanned((current) => current.filter((candidate) => !selectedScanned.includes(candidate.path)))
    } catch (error) {
      setFeedback(`导入失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const discoverMcps = async () => {
    if (!currentAgent) return
    setBusy(`mcp-discover:${currentAgent.id}`)
    try {
      const candidates = await onDiscoverMcps(currentAgent.id)
      setMcpCandidates(candidates)
      setSelectedMcps([])
      setFeedback(candidates.length ? `读取到 ${candidates.length} 个 MCP 配置；这里只读元数据，不启动服务。` : '没有发现可导入的 MCP 配置。')
    } catch (error) {
      setFeedback(`MCP 发现失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const importMcps = async () => {
    if (!currentAgent || selectedMcps.length === 0) return
    setBusy(`mcp-import:${currentAgent.id}`)
    try {
      const result = await onImportMcps(currentAgent.id, selectedMcps)
      setFeedback(`${result.imported?.length || 0} 个 MCP 已导入${result.errors?.length ? `；${result.errors.length} 个被拒绝` : ''}。默认不会启用或启动服务。`)
      setSelectedMcps([])
      setMcpCandidates((current) => current.filter((candidate) => !selectedMcps.includes(candidate.id)))
    } catch (error) {
      setFeedback(`MCP 导入失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const resetModelDraft = () => {
    setEditingModelId(null)
    setModelDraft({ cli_id: selectedAgentId || 'codex', model: '', alias: '', source: 'manual', efforts: [], default_effort: '', discovery_source: 'manual', credential_id: null, native_model_ref: null })
  }

  const resetServiceDraft = () => {
    setEditingServiceId(null)
    setServiceDraft({ name: '', provider: 'openai', api_format: 'openai-responses', endpoint: providerDefaultEndpoint('openai'), env_name: 'OPENAI_API_KEY', models: [] })
    setServiceCatalog([])
    setServiceQuery('')
    setServiceModelInput('')
    setServiceKey('')
    setServiceTest(null)
  }

  const applyServicePreset = (presetId: string) => {
    const preset = SERVICE_PRESETS.find((item) => item.id === presetId) || SERVICE_PRESETS[0]
    setEditingServiceId(null)
    setServiceDraft({ name: `${preset.label} 服务`, provider: preset.provider, api_format: preset.api_format, endpoint: preset.endpoint, env_name: preset.env_name, models: [] })
    setServiceCatalog([])
    setServiceKey('')
    setServiceTest(null)
  }

  const editService = (credential: Credential) => {
    const provider = credential.provider || 'custom'
    const apiFormat = credential.api_format || providerDefaultFormat(provider)
    setEditingServiceId(credential.id)
    setServiceDraft({
      name: credential.name || `${provider} 服务`,
      provider,
      api_format: apiFormat,
      endpoint: credential.endpoint || providerDefaultEndpoint(provider),
      env_name: apiFormatDefaultEnv(apiFormat),
      models: Array.isArray(credential.models) ? credential.models.map((model) => ({ id: model.id, alias: model.alias })) : [],
    })
    setServiceCatalog(Array.isArray(credential.models) ? credential.models : [])
    setServiceKey('')
    setServiceQuery('')
    setServiceModelInput('')
    setServiceTest(null)
    setTab('services')
  }

  const toggleServiceModel = (model: { id: string; alias: string }, checked: boolean) => {
    setServiceDraft((current) => ({ ...current, models: checked ? [...current.models.filter((item) => item.id !== model.id), model] : current.models.filter((item) => item.id !== model.id) }))
  }

  const updateVisibleServiceModels = (mode: 'all' | 'invert') => {
    const visible = filteredServiceModels
    const visibleIds = new Set(visible.map((model) => model.id))
    setServiceDraft((current) => {
      const hidden = current.models.filter((model) => !visibleIds.has(model.id))
      const visibleSelection = mode === 'all'
        ? visible
        : visible.filter((model) => !current.models.some((selected) => selected.id === model.id))
      return { ...current, models: [...hidden, ...visibleSelection] }
    })
  }

  const addServiceModel = () => {
    const id = serviceModelInput.trim()
    if (!id) return
    const model = { id, alias: id }
    setServiceCatalog((current) => current.some((item) => item.id === id) ? current : [...current, model])
    setServiceDraft((current) => ({ ...current, models: current.models.some((item) => item.id === id) ? current.models : [...current.models, model] }))
    setServiceModelInput('')
  }

  const testService = async () => {
    if (!editingServiceId && !serviceKey.trim()) {
      setFeedback('测试未保存服务前，请先输入 API key；测试已保存服务只会读取 Keychain。')
      return
    }
    setBusy('service-test')
    setServiceTest(null)
    try {
      const result = await onTestCredential(editingServiceId
        ? { credential_id: editingServiceId }
        : { provider: serviceDraft.provider, api_format: serviceDraft.api_format, env_name: serviceDraft.env_name, endpoint: serviceDraft.endpoint.trim(), api_key: serviceKey.trim() })
      setServiceTest(result)
      if (result.ok) setServiceCatalog(result.models || [])
      setFeedback(result.ok ? `服务目录连接成功：${result.models?.length || result.model_count || 0} 个模型；这不代表已完成模型推理。` : `服务目录未通过：${result.message}`)
    } catch (error) {
      setFeedback(`服务目录测试失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const saveService = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!serviceDraft.name.trim() || !serviceDraft.endpoint.trim() && serviceDraft.provider === 'custom') {
      setFeedback('请填写服务名称；Custom 服务还需要 Endpoint。')
      return
    }
    setBusy('service-save')
    try {
      const payload = { ...serviceDraft, name: serviceDraft.name.trim(), endpoint: serviceDraft.endpoint.trim(), models: serviceDraft.models, api_key: serviceKey.trim() }
      const saved = editingServiceId
        ? await onUpdateCredential(editingServiceId, payload)
        : serviceKey.trim() ? await onStoreCredential({ ...payload, api_key: serviceKey.trim() }) : null
      if (!saved) {
        setFeedback('新服务必须输入 API key；密钥只用于本次 Keychain 写入。')
        return
      }
      setFeedback(editingServiceId ? '服务元数据已更新；空 key 保留原 Keychain 引用。' : '服务已保存；多个 Agent 可复用同一服务与模型别名。')
      resetServiceDraft()
    } catch (error) {
      setFeedback(`服务保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const editModel = (model: AgentModel) => {
    setEditingModelId(model.id)
    setModelDraft({ cli_id: model.cli_id, model: model.model, alias: model.alias, source: model.source, efforts: model.efforts?.length ? [...model.efforts] : [], default_effort: model.default_effort || '', discovery_source: model.discovery_source || 'manual', credential_id: model.credential_id || null, native_model_ref: model.native_model_ref || null })
    setTab('models')
  }

  const chooseNativeModel = (model: AgentModel) => {
    setEditingModelId(null)
    setModelDraft({
      cli_id: model.cli_id,
      model: model.model,
      alias: model.alias,
      source: 'manual',
      efforts: model.efforts?.length ? [...model.efforts] : [],
      default_effort: model.default_effort || '',
      discovery_source: model.discovery_source || 'native discovery',
      credential_id: null,
      native_model_ref: model.id,
    })
  }

  const saveModel = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!modelDraft.model.trim() || !modelDraft.alias.trim()) return
    if (modelDraft.source === 'manual' && !modelDraft.native_model_ref && !editingModelId) {
      setFeedback('登录态模型必须从当前 Agent 的本机 CLI 目录中选择；旧版手填记录只能编辑已有配置。')
      return
    }
    if (modelDraft.source === 'api') {
      const credential = knownCredentials.find((item) => item.id === modelDraft.credential_id)
      if (!credential) {
        setFeedback('API 模型必须选择一个已配置的服务；请先在“AI 服务”中保存并测试目录。')
        return
      }
      if (!serviceCompatible(modelDraft.cli_id, credential)) {
        setFeedback(`当前 Agent 不兼容所选服务协议 ${credentialApiFormat(credential)}；请选择已验证的服务。`)
        return
      }
    }
    setBusy('model-save')
    try {
      if (editingModelId) {
        const payload: Partial<AgentModel> = editingModelIsNative
          ? { alias: modelDraft.alias.trim(), default_effort: modelDraft.default_effort || '' }
          : editingModelIsLogin
            ? { alias: modelDraft.alias.trim(), default_effort: modelDraft.default_effort || '' }
          : modelDraft
        await onUpdateModel(editingModelId, payload)
      }
      else {
        const payload: AgentModelInput = modelDraft.native_model_ref
          ? { cli_id: modelDraft.cli_id, model: modelDraft.model.trim(), alias: modelDraft.alias.trim(), source: 'manual', native_model_ref: modelDraft.native_model_ref, default_effort: modelDraft.default_effort || '' }
          : { ...modelDraft, model: modelDraft.model.trim(), alias: modelDraft.alias.trim() }
        await onCreateModel(payload)
      }
      setFeedback(editingModelId ? '模型记录已更新。' : '模型记录已创建。')
      resetModelDraft()
    } catch (error) {
      setFeedback(`模型保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="settings-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose() }}>
      <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="global-settings-title">
        <header className="settings-header">
          <div><span className="eyebrow">GLOBAL WORKSPACE</span><h2 id="global-settings-title">全局设置</h2><p>Agent、模型/API 与外观只在这里配置；节点只保存可复用的引用。</p></div>
          <button className="icon-button" onClick={onClose} title="关闭设置"><X size={17} /></button>
        </header>
        <nav className="settings-tabs" aria-label="全局设置分区">
          <button className={tab === 'agents' ? 'settings-tab active' : 'settings-tab'} onClick={() => setTab('agents')}><MonitorCog size={15} />Agent 配置</button>
          <button className={tab === 'services' ? 'settings-tab active' : 'settings-tab'} onClick={() => setTab('services')}><Server size={15} />AI 服务</button>
          <button className={tab === 'models' ? 'settings-tab active' : 'settings-tab'} onClick={() => setTab('models')}><KeyRound size={15} />模型 / API</button>
          <button className={tab === 'defaults' ? 'settings-tab active' : 'settings-tab'} onClick={() => setTab('defaults')}><SlidersHorizontal size={15} />新建默认值</button>
          <button className={tab === 'appearance' ? 'settings-tab active' : 'settings-tab'} onClick={() => setTab('appearance')}><Search size={15} />外观</button>
        </nav>
        {feedback && <div className="settings-feedback"><CircleAlert size={14} />{feedback}</div>}
        <div className="settings-content">
          {tab === 'agents' && <>
            <div className="settings-grid settings-agent-grid">
              <div className="settings-list-card">
                <div className="settings-card-heading"><div><span className="field-caption">AVAILABLE AGENTS</span><strong>全局 Agent</strong></div><div className="settings-heading-actions"><span className="settings-count">{agents.filter((agent) => agent.available).length} 可用</span><button className="outline-button compact-button" type="button" onClick={() => void refreshAllAgents()} disabled={busy === 'discover-all'}><RefreshCw size={13} className={busy === 'discover-all' ? 'spin' : ''} />检查并刷新全部</button></div></div>
                <p className="helper-copy">只读刷新版本、模型目录和 effort；登录态另行检查，不启动登录流程，也不代表模型可计费。</p>
                <div className="agent-list">{agents.map((agent) => <button key={agent.id} className={agent.id === selectedAgentId ? 'agent-row selected' : 'agent-row'} onClick={() => selectAgent(agent.id)}><span className={`status-dot ${agent.available ? 'agent-ready' : ''}`} /><span className="agent-row-copy"><strong title={agent.label}>{agent.label}</strong><small>{agent.version || agent.status || '未发现'}{agent.login?.status ? ` · 登录${agent.login.status === 'verified' ? '已确认' : agent.login.status === 'not_logged_in' ? '未登录' : '未知'}` : ''}</small></span><ChevronDown size={13} /></button>)}</div>
              </div>
              {currentAgent && <div className="settings-editor-card">
                <div className="settings-card-heading"><div><span className="field-caption">AGENT PROFILE</span><strong title={currentAgent.label}>{currentAgent.label}</strong></div><button className="outline-button compact-button" type="button" onClick={() => void discover(currentAgent.id)} disabled={busy === `discover:${currentAgent.id}` || busy === 'discover-all'}><RefreshCw size={13} className={busy === `discover:${currentAgent.id}` ? 'spin' : ''} />检查并刷新</button></div>
                <p className="helper-copy">只保存此 Agent 的本地可执行文件与选定 Skill 根目录，不会链接、安装或改写宿主全局配置。模型目录失败时保留已有目录与已保存绑定。</p>
                {currentAgent.login && <div className={`login-status-card login-${currentAgent.login.status}`}><div><span className="field-caption">LOGIN STATUS</span><strong>{currentAgent.login.status === 'verified' ? '已确认登录' : currentAgent.login.status === 'not_logged_in' ? '未登录' : currentAgent.login.status === 'unsupported' ? '未知（未验证）' : '未知'}</strong></div><small>{currentAgent.login.reason || '尚未检查登录态'}{currentAgent.login.checked_at ? ` · ${new Date(currentAgent.login.checked_at).toLocaleString()}` : ''}</small><small>证据：{currentAgent.login.evidence || '未检查'} · 来源：{currentAgent.login.source || '未检查'} · 不展示或保存命令中的凭据/账户信息；CLI 自身会读取登录凭据</small></div>}
                <Field label="可执行文件" hint={currentAgent.available ? `${currentAgent.status}${currentAgent.version ? ` · ${currentAgent.version}` : ''}` : currentAgent.message || '不可用'}><div className="picker-row"><input title={currentAgent.executable || '尚未选择可执行文件'} value={currentAgent.executable} placeholder="选择本机可执行文件" onChange={(event) => updateAgentDraft({ executable: event.target.value })} /><button className="outline-button" onClick={() => void chooseExecutable()}><FolderOpen size={14} />选择</button></div></Field>
                <div className="settings-subsection runtime-settings-block">
                  <div className="settings-card-heading"><div><span className="field-caption">AGENT RUNTIME</span><strong>解释器与真实启动检测</strong></div><button className="outline-button compact-button" type="button" onClick={() => void probeRuntime()} disabled={busy === `runtime:${currentAgent.id}`}><RefreshCw size={13} className={busy === `runtime:${currentAgent.id}` ? 'spin' : ''} />检查 runtime</button></div>
                  <Field label="固定解释器（可选）" hint="填写绝对路径；Node CLI 会优先尝试本机已存在的候选。不会安装依赖，也不会改全局 PATH。"><input value={currentAgent.runtime_interpreter || ''} placeholder="如 /Users/.../.local/bin/node" onChange={(event) => updateAgentDraft({ runtime_interpreter: event.target.value || null })} /></Field>
                  <div className={`status-box runtime-status-box ${currentAgent.runtime?.status === 'READY' ? 'runtime-ready' : currentAgent.runtime?.status && currentAgent.runtime.status !== 'unknown' ? 'runtime-warning' : ''}`}><div><span className={`status-dot ${currentAgent.runtime?.status === 'READY' ? 'status-online' : ''}`} />{currentAgent.runtime?.status === 'READY' ? 'runtime 已通过' : 'runtime 尚未确认'}</div><span className="status-muted">{currentAgent.runtime?.version || currentAgent.runtime?.status || '等待检查'}</span><small>{currentAgent.runtime?.interpreter || '自动候选（Node CLI）'}{currentAgent.runtime?.interpreter_version ? ` · ${currentAgent.runtime.interpreter_version}` : ''}{currentAgent.runtime?.message ? ` · ${currentAgent.runtime.message}` : ''}</small></div>
                  <p className="helper-copy">当前绑定会同时用于版本探测、实际 CLI 启动与快照恢复。Pi/Node CLI 只使用已找到且可执行的本机解释器；失败会标记为 runtime dependency failure，不会伪装成 API 登录问题。</p>
                </div>
                <div className="field-caption">Skill 根目录</div>
                <div className="path-list">{currentAgent.skill_roots.length === 0 ? <span className="empty-note">还没有绑定目录。扫描只会读取这里列出的根目录。</span> : currentAgent.skill_roots.map((path) => <div className="path-chip" key={path} title={path}><FolderOpen size={13} /><span>{path}</span><button title="移除目录" onClick={() => updateAgentDraft({ skill_roots: currentAgent.skill_roots.filter((item) => item !== path) })}><X size={12} /></button></div>)}</div>
                <button className="outline-button full-width" onClick={() => void addSkillRoot()}><Plus size={14} />添加 Skill 文件夹</button>
                <div className="settings-actions"><button className="outline-button" onClick={() => void scanSkills()} disabled={busy === `scan:${currentAgent.id}`}><Search size={14} />扫描 Skills</button><button className="run-button" onClick={() => void saveAgent()} disabled={busy === `save:${currentAgent.id}`}><Save size={14} />保存 Agent</button></div>
                <div className="settings-subsection">
                  <div className="settings-card-heading"><div><span className="field-caption">SKILL DISCOVERY</span><strong>扫描结果</strong></div><span className="settings-count">{selectedScanned.length} 已选</span></div>
                  <div className="skill-discovery-toolbar">
                    <label className="toolbar-search"><Search size={13} /><input aria-label="搜索 Skill 名" value={skillQuery} onChange={(event) => setSkillQuery(event.target.value)} placeholder="搜索 Skill 名" /></label>
                    <label><span className="sr-only">Skill 排序</span><select aria-label="Skill 排序" value={skillSort} onChange={(event) => setSkillSort(event.target.value as 'name' | 'modified_at')}><option value="name">名称</option><option value="modified_at">修改日期</option></select></label>
                    <button className="icon-button sort-direction" type="button" title={`按${skillSort === 'name' ? '名称' : '修改日期'}${skillSortDirection === 'asc' ? '降序' : '升序'}排列`} aria-label="切换 Skill 排序方向" onClick={() => setSkillSortDirection((current) => current === 'asc' ? 'desc' : 'asc')}><ArrowDownUp size={14} /></button>
                  </div>
                  {scanned.length === 0 ? <p className="empty-note">点击“扫描 Skills”，检查名称、描述、修改日期和来源后再导入。</p> : filteredScanned.length === 0 ? <p className="empty-note">没有匹配的 Skill；已勾选项仍会在清除筛选后保留。</p> : <div className="candidate-list">{filteredScanned.map((candidate) => <label key={candidate.path} className={selectedScanned.includes(candidate.path) ? 'candidate-row selected' : 'candidate-row'}><input type="checkbox" checked={selectedScanned.includes(candidate.path)} onChange={(event) => setSelectedScanned((current) => event.target.checked ? current.includes(candidate.path) ? current : [...current, candidate.path] : current.filter((path) => path !== candidate.path))} /><span><strong title={candidate.name}>{candidate.name}</strong><small>{candidate.description || '无描述'} · {candidate.source || candidate.path} · {candidate.modified_at ? new Date(candidate.modified_at).toLocaleString() : '修改日期未提供'}</small></span></label>)}</div>}
                  <button className="outline-button full-width" onClick={() => void importSkills()} disabled={!selectedScanned.length || busy === `import:${currentAgent.id}`}><ShieldCheck size={14} />导入选中的 Skill 快照</button>
                </div>
                <div className="settings-subsection">
                  <div className="settings-card-heading"><div><span className="field-caption">MCP INVENTORY</span><strong>按需发现与导入</strong></div><span className="settings-count">{mcps.length} 已导入</span></div>
                  <p className="helper-copy">默认不启用、不扫描、不启动服务。点击后只读取该 Agent 已配置的公开元数据。</p>
                  <div className="settings-actions"><button className="outline-button" onClick={() => void discoverMcps()} disabled={busy === `mcp-discover:${currentAgent.id}`}><Server size={14} />发现 MCP（仅读取配置）</button><button className="outline-button" onClick={() => void importMcps()} disabled={!selectedMcps.length || busy === `mcp-import:${currentAgent.id}`}><ShieldCheck size={14} />导入勾选项</button></div>
                  {mcpCandidates.length > 0 ? <div className="candidate-list mcp-candidate-list">{mcpCandidates.map((candidate) => <label key={candidate.id} className={`candidate-row ${selectedMcps.includes(candidate.id) ? 'selected' : ''} ${candidate.supported === false ? 'unsupported' : ''}`}><input type="checkbox" disabled={candidate.supported === false} checked={selectedMcps.includes(candidate.id)} onChange={(event) => setSelectedMcps((current) => event.target.checked ? [...current, candidate.id] : current.filter((id) => id !== candidate.id))} /><span><strong title={candidate.name}>{candidate.name}</strong><small>{candidate.transport || 'transport 未声明'} · {candidate.supported === false ? `不支持：${candidate.reason || '目标 Agent 不支持'}` : candidate.reason || '可导入；不会自动启用'}</small></span></label>)}</div> : <p className="empty-note">尚未读取 MCP 列表。</p>}
                  {mcps.length > 0 && <div className="imported-mcp-list">{mcps.map((mcp) => <span className="mcp-pill" key={mcp.id}><Server size={11} />{mcp.name}<small>{mcp.source_agent || 'unknown'}</small></span>)}</div>}
                </div>
              </div>}
            </div>
          </>}
          {tab === 'services' && <div className="settings-grid settings-service-grid">
            <div className="settings-list-card">
              <div className="settings-card-heading"><div><span className="field-caption">GLOBAL AI SERVICES</span><strong>可复用服务</strong></div><span className="settings-count">{serviceList.length} 条</span></div>
              <p className="helper-copy">服务元数据独立于 Agent 模型记录；同一个 Keychain credential 可以被多个兼容的 Agent 与模型 alias 复用。</p>
              {serviceList.length === 0 ? <p className="empty-note">还没有保存服务。右侧编辑器只会在你提交后写入 Keychain。</p> : <div className="model-list service-list">{serviceList.map((credential) => <div className="model-row service-row" key={credential.id}><div className="model-copy"><strong title={credential.name || credential.provider}>{credential.name || `${credential.provider || 'Custom'} 服务`}</strong><span>{credential.provider || 'custom'} · {credential.api_format || 'openai-chat-completions'}</span><small>{credential.endpoint || '使用 provider 默认地址'} · {credential.models?.length || 0} 个模型 · {credential.configured ? 'Keychain 已配置' : 'Keychain 待配置'}</small></div><button className="outline-button compact-button" type="button" onClick={() => editService(credential)}>编辑</button></div>)}</div>}
            </div>
            <div className="settings-editor-card service-editor">
              <div className="settings-card-heading"><div><span className="field-caption">SERVICE EDITOR</span><strong>{editingServiceId ? '编辑 AI 服务' : '新增 AI 服务'}</strong></div>{editingServiceId && <button className="text-button" type="button" onClick={resetServiceDraft}>取消编辑</button>}</div>
              <p className="helper-copy">这里只保存 provider、协议、Endpoint、模型目录和 Keychain 的不透明引用；服务测试只读取模型目录，不代表完成推理。</p>
              <form onSubmit={saveService}>
                <Field label="服务预设"><select aria-label="服务预设" value={servicePresetValue} onChange={(event) => applyServicePreset(event.target.value)}>{SERVICE_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}</select></Field>
                <Field label="服务名称" hint="给多个 Agent 复用的友好名称"><input required value={serviceDraft.name} onChange={(event) => setServiceDraft((current) => ({ ...current, name: event.target.value }))} placeholder="如 研究用 Google AI Studio" /></Field>
                <div className="two-fields">
                  <Field label="Provider"><select value={serviceDraft.provider} onChange={(event) => { const provider = event.target.value; setServiceDraft((current) => ({ ...current, provider, api_format: providerDefaultFormat(provider), env_name: providerDefaultEnv(provider), endpoint: providerDefaultEndpoint(provider) })); setServiceTest(null) }}><option value="custom">Custom / 兼容代理</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="google">Google AI Studio</option></select></Field>
                  <Field label="API 协议"><select value={serviceDraft.api_format} onChange={(event) => { const apiFormat = event.target.value; setServiceDraft((current) => ({ ...current, api_format: apiFormat, env_name: apiFormatDefaultEnv(apiFormat) })); setServiceTest(null) }}><option value="openai-chat-completions">OpenAI Chat Completions</option><option value="openai-responses">OpenAI Responses</option><option value="anthropic-messages">Anthropic Messages</option><option value="google-generative-ai">Google Generative AI</option></select></Field>
                </div>
                <Field label="Endpoint" hint={serviceDraft.provider === 'custom' ? 'Custom 必须填写 HTTPS 基础地址。' : '保存的服务测试会锁定这里的地址，不接受前端另传目标。'}><input required={serviceDraft.provider === 'custom'} type="url" value={serviceDraft.endpoint} autoComplete="off" onChange={(event) => { setServiceDraft((current) => ({ ...current, endpoint: event.target.value })); setServiceTest(null) }} placeholder="HTTPS API 基础地址" /></Field>
                <Field label="API key" hint={editingServiceId ? `留空保留现有 key；更换 Endpoint / 协议时必须重新输入。当前协议使用 ${serviceDraft.env_name}。` : `只用于本次安全写入，不进入数据库、工作流或导出。当前协议使用 ${serviceDraft.env_name}。`}><input type="password" value={serviceKey} autoComplete="new-password" spellCheck={false} onChange={(event) => { setServiceKey(event.target.value); setServiceTest(null) }} placeholder={editingServiceId ? '留空保留现有 key' : '只用于本次安全写入'} /></Field>
                <div className="service-catalog">
                  <div className="settings-card-heading"><div><span className="field-caption">MODEL CATALOG</span><strong>模型与 alias</strong></div><span className="settings-count">{serviceDraft.models.length} 已选</span></div>
                  <div className="service-catalog-toolbar"><label className="toolbar-search"><Search size={13} /><input aria-label="搜索服务模型" value={serviceQuery} onChange={(event) => setServiceQuery(event.target.value)} placeholder="搜索模型 ID / alias" /></label><button className="outline-button compact-button" type="button" disabled={busy === 'service-test' || (!editingServiceId && !serviceKey.trim())} onClick={() => void testService()}><RefreshCw size={13} className={busy === 'service-test' ? 'spin' : ''} />测试 /models</button></div>
                  <div className="selection-scope-row"><span>范围：当前搜索可见模型（{filteredServiceModels.length}）</span><button className="mini-button" type="button" disabled={filteredServiceModels.length === 0} onClick={() => updateVisibleServiceModels('all')}>全选当前</button><button className="mini-button" type="button" disabled={filteredServiceModels.length === 0} onClick={() => updateVisibleServiceModels('invert')}>反选当前</button></div>
                  {serviceTest && <div className={serviceTest.ok ? 'connection-result ok' : 'connection-result error'}><span>{serviceTest.ok ? <CircleCheck size={13} /> : <CircleX size={13} />}</span><div><strong>{serviceTest.ok ? '目录连接成功' : '目录未通过 · ' + serviceTest.status}</strong><small>{serviceTest.message} · {serviceTest.models?.length || serviceTest.model_count || 0} 个可用模型；不代表已完成模型推理。</small></div></div>}
                  {filteredServiceModels.length === 0 ? <p className="empty-note">尚无目录结果；可以先测试 /models，也可以在下方添加明确的模型 ID。</p> : <div className="service-model-list">{filteredServiceModels.map((model) => <label className="service-model-row" key={model.id}><input type="checkbox" checked={serviceDraft.models.some((item) => item.id === model.id)} onChange={(event) => toggleServiceModel(model, event.target.checked)} /><span><strong title={model.id}>{model.alias || model.id}</strong><small>{model.id}</small></span></label>)}</div>}
                  <div className="service-custom-model"><input aria-label="添加服务模型 ID" value={serviceModelInput} onChange={(event) => setServiceModelInput(event.target.value)} placeholder="手动添加模型 ID" /><button className="outline-button compact-button" type="button" onClick={addServiceModel} disabled={!serviceModelInput.trim()}><Plus size={13} />添加</button></div>
                  {serviceDraft.models.length > 0 && <div className="service-selected-models">{serviceDraft.models.map((model) => <span className="mcp-pill" key={model.id}>{model.alias || model.id}</span>)}</div>}
                </div>
                <div className="service-compat-note"><ShieldCheck size={14} /><span>兼容性由运行时严格校验：Codex 仅 OpenAI Responses，Claude 仅 Anthropic Messages；当前已验证 pi 的 Google task-local models.json 映射，未验证组合会被拒绝，不会静默回退。</span></div>
                <div className="settings-actions"><button className="outline-button" type="button" onClick={resetServiceDraft}>清空编辑器</button><button className="run-button" type="submit" disabled={busy === 'service-save' || !serviceDraft.name.trim() || (serviceDraft.provider === 'custom' && !serviceDraft.endpoint.trim()) || (!editingServiceId && !serviceKey.trim())}><Save size={14} />{editingServiceId ? '保存服务' : '写入 Keychain 并保存'}</button></div>
              </form>
            </div>
          </div>}
          {tab === 'models' && <div className="settings-grid settings-model-grid">
            <div className="mode-explanation settings-mode-explanation">
              <strong>{sourceLabel(modelDraft.source, modelDraft.native_model_ref, modelDraft.credential_id, !editingModelId)}模式</strong>
              <span>{sourceDescription(modelDraft.source, modelDraft.native_model_ref, modelDraft.credential_id, !editingModelId)}</span>
            </div>
            <div className="settings-list-card">
              <div className="settings-card-heading"><div><span className="field-caption">NATIVE MODEL CATALOG</span><strong>本机 CLI 模型目录</strong></div><span className="settings-count">{nativeCatalogModels.length} 个</span></div>
              <p className="helper-copy">模型和 effort 只来自当前 Agent 的本机 discovery；选择后可保存多个独立 alias / 默认 effort 配置。目录刷新不会覆盖已保存配置。</p>
              {nativeCatalogModels.length === 0 ? <div className="empty-note">当前 Agent 没有可用的本机 CLI 模型目录；登录态配置不可创建，请检查 CLI 或切换到 API 模式。</div> : <div className="model-list native-model-list">{nativeCatalogModels.map((model) => <div className="model-row native-catalog-row" key={model.id}><div className="model-copy"><strong title={model.alias}>{model.alias}</strong><span title={model.model}>{model.model}</span><small>{model.cli_id} · 原生目录 · {(model.efforts || []).join(' / ') || 'effort 未声明'}</small></div><button className="outline-button compact-button" type="button" onClick={() => chooseNativeModel(model)}>选择</button></div>)}</div>}
              <div className="settings-subsection model-configured-subsection">
                <div className="settings-card-heading"><div><span className="field-caption">SAVED CONFIGURATIONS</span><strong>已保存模型配置</strong></div><span className="settings-count">{configuredModels.length} 条</span></div>
                {configuredModels.length === 0 ? <p className="empty-note">还没有保存的配置；从上方目录选择一个模型后创建。</p> : <div className="model-list">{configuredModels.map((model) => <div className="model-row" key={model.id}><div className="model-copy"><strong title={model.alias}>{model.alias}</strong><span title={model.model}>{model.model}</span><small>{model.cli_id} · {sourceLabel(model.source, model.native_model_ref, model.credential_id)} · {(model.efforts || []).join(' / ') || '未声明 effort'}{model.default_effort ? ` · 默认 ${model.default_effort}` : ''}</small></div><div className="model-actions"><button className="icon-button" type="button" onClick={() => editModel(model)} title="编辑模型"><Save size={13} /></button><button className="danger-icon" type="button" onClick={() => { if (window.confirm(`删除模型 ${model.alias}？`)) void onDeleteModel(model.id) }} title="删除模型"><Trash2 size={13} /></button></div></div>)}</div>}
              </div>
            </div>
            <div className="settings-editor-card settings-model-editor">
              <div className="settings-card-heading"><div><span className="field-caption">MODEL / API ENTRY</span><strong>{editingModelId ? '编辑模型配置' : '添加模型配置'}</strong></div>{editingModelId && <button className="text-button" type="button" onClick={resetModelDraft}>取消编辑</button>}</div>
              <form onSubmit={saveModel}>
                <div className="two-fields">
                  <Field label="绑定 Agent"><select aria-label="绑定 Agent" value={modelDraft.cli_id} disabled={Boolean(editingModelId)} onChange={(event) => selectAgent(event.target.value)}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.label}</option>)}</select></Field>
                  <Field label="来源"><select aria-label="来源" value={modelDraft.source} disabled={Boolean(editingModelId)} onChange={(event) => { const source = event.target.value; setModelDraft((current) => ({ ...current, source, model: '', alias: '', efforts: [], default_effort: '', credential_id: null, native_model_ref: null, discovery_source: source === 'api' ? 'user API model' : 'native discovery' })) }}>{editingModelId && modelDraft.source === 'native' && <option value="native">原生目录（只读）</option>}<option value="api">API</option><option value="manual">登录态（本机 CLI）</option></select></Field>
                </div>
                <Field label="显示 alias" hint="用于节点和全局模型下拉框；同一个实际模型可保存多个 alias"><input required value={modelDraft.alias} onChange={(event) => setModelDraft((current) => ({ ...current, alias: event.target.value }))} placeholder="如 慎思 · 本机 CLI" /></Field>
                <Field label="实际模型标识" hint={modelDraftIsLogin ? '从当前 Agent 的本机 CLI 目录选择；不会接受客户端伪造的模型或 effort。' : 'API / 历史配置可填写真实模型 ID。'}>{modelDraftIsLogin ? <select aria-label="实际模型标识" required value={modelDraft.native_model_ref || ''} onChange={(event) => { const model = nativeCatalogModels.find((item) => item.id === event.target.value); if (model) chooseNativeModel(model); else setModelDraft((current) => ({ ...current, model: '', alias: '', efforts: [], default_effort: '', credential_id: null, native_model_ref: null })) }}><option value="">选择本机 CLI 模型…</option>{nativeCatalogModels.map((model) => <option key={model.id} value={model.id}>{model.alias} · {model.model}</option>)}</select> : <input aria-label="实际模型标识" required disabled={editingModelIsNative} value={modelDraft.model} onChange={(event) => setModelDraft((current) => ({ ...current, model: event.target.value }))} placeholder="如 gpt-5.6 / provider/model" />}</Field>
                <Field label="支持的 effort" hint={modelDraftIsLogin ? '由所选本机模型目录声明，不能手工扩展。' : '只填已验证支持的值，用逗号分隔'}><input disabled={modelDraftIsLogin || editingModelIsNative} value={modelDraft.efforts.join(', ')} onChange={(event) => setModelDraft((current) => ({ ...current, efforts: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) }))} placeholder="如 low, medium, high" /></Field>
                <Field label="默认 effort"><select aria-label="默认 effort" value={modelDraft.default_effort || ''} onChange={(event) => setModelDraft((current) => ({ ...current, default_effort: event.target.value }))}><option value="">Agent 默认 / 未设置</option>{modelDraft.efforts.map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></Field>
                <Field label="服务引用" hint={modelDraftIsLogin ? '本机登录态不绑定服务；服务只适用于 API 模型。' : modelDraft.source === 'api' ? agentApiCompatibilityHint(modelDraft.cli_id) : '密钥本体永不进入模型记录。'}><select disabled={modelDraftIsLogin || editingModelIsNative} value={modelDraft.credential_id || ''} onChange={(event) => setModelDraft((current) => ({ ...current, credential_id: event.target.value || null }))}><option value="">使用 CLI 已有登录</option>{knownCredentials.map((credential) => { const compatible = serviceCompatible(modelDraft.cli_id, credential); return <option key={credential.id} value={credential.id} disabled={!compatible}>{credential.name || credential.provider} · {credentialApiFormat(credential)}{compatible ? '' : ' · 当前 Agent 不兼容'}</option> })}</select></Field>
                {modelDraft.source === 'api' && selectedModelService && (selectedModelService.models?.length || 0) > 0 && <Field label="服务模型目录" hint="选择只会填入实际模型 ID；运行时仍会再次校验服务目录。"><select aria-label="服务模型目录" value={selectedModelService.models?.some((item) => item.id === modelDraft.model) ? modelDraft.model : ''} onChange={(event) => { const model = selectedModelService.models?.find((item) => item.id === event.target.value); if (model) setModelDraft((current) => ({ ...current, model: model.id, alias: current.alias || model.alias })) }}><option value="">手动输入模型 ID…</option>{selectedModelService.models?.map((model) => <option key={model.id} value={model.id}>{model.alias || model.id} · {model.id}</option>)}</select></Field>}
                <button className="run-button full-width" type="submit" disabled={busy === 'model-save' || !modelDraft.model.trim() || !modelDraft.alias.trim() || (modelDraftIsLogin && !modelDraft.native_model_ref)}><Save size={14} />{editingModelId ? '保存模型' : '创建模型'}</button>
              </form>
              {modelDraftIsLogin ? <div className="status-box"><div><span className="status-dot status-online" />登录态模型配置</div><span className="status-muted">实际模型与 effort 来自本机 CLI 目录；这里只保存 alias、默认 effort 和 native_model_ref，不保存密钥。</span></div> : editingModelIsNative ? <div className="status-box"><div><span className="status-dot" />原生目录记录</div><span className="status-muted">CLI、模型标识、effort 和服务引用由 Agent discovery 管理。</span></div> : <div className="credential-form global-credential-form"><div className="field-caption"><Server size={13} />全局 AI 服务</div><p className="helper-copy">服务的保存、编辑、模型目录测试和 Keychain 写入统一在“AI 服务”中完成；这里仅绑定不透明的服务引用。</p><button className="outline-button full-width" type="button" onClick={() => { resetServiceDraft(); setTab('services') }}><Server size={14} />管理 AI 服务</button></div>}
            </div>
          </div>}
          {tab === 'defaults' && <div className="settings-grid settings-default-grid">
            <div className="settings-editor-card">
              <div className="settings-card-heading"><div><span className="field-caption">NEW ANALYZER DEFAULT</span><strong>默认分析器</strong></div><span className="settings-count">仅影响新建</span></div>
              <p className="helper-copy">新建分析器，以及新建有界循环中的执行器和审阅器，会读取这里的默认值。已有节点、导入流程、模板明确绑定和自定义预设不会被改写。</p>
              <div className={`default-effective-card ${defaultAnalyzer.status === 'missing' ? 'missing' : ''}`}><div><span className="field-caption">CURRENT EFFECTIVE DEFAULT</span><strong>{defaultSummary}</strong></div><small>{defaultAnalyzer.status === 'missing' ? `绑定不可用：${defaultAnalyzer.reason || '请重新选择或清除固定模型。'}` : defaultAnalyzer.reason || '当前默认值可用。'}</small></div>
              <Field label="默认方式"><select value={defaultMode} onChange={(event) => { const mode = event.target.value as 'cli' | 'model'; setDefaultMode(mode); if (mode === 'cli') { setDefaultModelRef(''); setDefaultEffort('') } }}><option value="cli">使用 Agent 默认模型</option><option value="model">固定已保存模型绑定</option></select></Field>
              <Field label="默认 Agent" hint="plain CLI 只保存 Agent ID；不可用时显示缺失，不静默替换"><select value={defaultAgentId} onChange={(event) => { setDefaultAgentId(event.target.value); if (defaultMode === 'model') { setDefaultModelRef(''); setDefaultEffort('') } }}>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.label}{agent.available ? '' : ' · 当前不可用'}</option>)}</select></Field>
              {defaultMode === 'model' && <>
                <Field label="固定模型绑定" hint="alias、实际模型和 credential 均由后端按 model_ref 派生；不会保存 key"><select value={defaultModelRef} onChange={(event) => { const value = event.target.value; const model = models.find((item) => item.id === value); setDefaultModelRef(value); if (model) { setDefaultAgentId(model.agent_id || model.cli_id); setDefaultEffort(model.default_effort || '') } }}><option value="">选择已保存模型…</option>{defaultModelRef && !models.some((model) => model.id === defaultModelRef && (model.source !== 'native' || Boolean(model.native_model_ref))) && <option value={defaultModelRef}>绑定已不可用 · 需重新选择</option>}{models.filter((model) => model.source !== 'native' || Boolean(model.native_model_ref)).map((model) => <option key={model.id} value={model.id}>{model.alias} · {model.model} · {model.agent_id || model.cli_id}</option>)}</select></Field>
                <Field label="默认 effort"><select value={defaultEffort} onChange={(event) => setDefaultEffort(event.target.value)}><option value="">模型默认 effort</option>{defaultEffort && !defaultEffortOptions.includes(defaultEffort) && <option value={defaultEffort}>{defaultEffort} · 当前记录不再支持</option>}{defaultEffortOptions.map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></Field>
              </>}
              <Field label="默认提示词模板" hint="保留当前内置模板作为可恢复选项；选择自定义后可编辑，空字符串也会原样保存"><select aria-label="默认提示词模板" value={defaultPrompt === DEFAULT_ANALYZER_PROMPT ? 'builtin' : 'custom'} onChange={(event) => { if (event.target.value === 'builtin') setDefaultPrompt(DEFAULT_ANALYZER_PROMPT); else setDefaultPrompt((current) => current === DEFAULT_ANALYZER_PROMPT ? '' : current) }}><option value="builtin">当前内置默认提示词（恢复）</option><option value="custom">自定义提示词</option></select></Field>
              <Field label="默认分析提示词"><textarea aria-label="默认分析提示词" rows={8} value={defaultPrompt} onChange={(event) => setDefaultPrompt(event.target.value)} /></Field>
              <div className="settings-actions"><button className="mini-button" type="button" onClick={() => setDefaultPrompt(DEFAULT_ANALYZER_PROMPT)}>恢复当前内置默认提示词</button><span className="settings-count">{defaultPrompt.length} 字</span></div>
              <div className="settings-actions"><button className="outline-button" type="button" onClick={() => void clearDefaultAnalyzer()} disabled={busy === 'default-analyzer-save'}>清除固定模型并回退</button><button className="run-button" type="button" onClick={() => void saveDefaultAnalyzer()} disabled={busy === 'default-analyzer-save'}><Save size={14} />保存默认分析器</button></div>
            </div>
            <div className="settings-editor-card">
              <div className="settings-card-heading"><div><span className="field-caption">NEW OUTPUT CONTAINER DEFAULT</span><strong>输出容器默认值</strong></div><span className="settings-count">仅影响新建</span></div>
              <p className="helper-copy">只为之后新建的输出容器填入默认值；旧节点已有的正文格式、接收扩展名、JSON 模式和历史运行快照保持不变。</p>
              <div className="field-caption">正文副本格式</div>
              <div className="format-check-list">{(['markdown', 'text', 'json'] as const).map((format) => { const checked = outputDraft.export_formats.includes(format); const label = format === 'markdown' ? 'Markdown（.md）' : format === 'text' ? '纯文本（.txt）' : 'JSON（.json）'; return <label key={format} className={`check-field compact-check ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={(event) => setOutputDraft((current) => ({ ...current, export_formats: event.target.checked ? [...current.export_formats, format] : current.export_formats.filter((item) => item !== format) }))} /><span>{label}</span></label> })}</div>
              <div className="field-caption">真实生成文件接收扩展名</div>
              <p className="helper-copy">只接收 Agent 在运行 workspace 的 outputs/ 中真实生成的文件；不会把正文转换成这些扩展名。</p>
              <div className="selection-scope-row"><span>{outputDraft.allowed_file_extensions.length ? `已允许 ${outputDraft.allowed_file_extensions.length} 项` : '当前不接收生成文件'}</span><button className="mini-button" type="button" onClick={() => setOutputDraft((current) => ({ ...current, allowed_file_extensions: [...generatedExtensions] }))}>全选</button><button className="mini-button" type="button" onClick={() => setOutputDraft((current) => ({ ...current, allowed_file_extensions: [] }))}>清空</button></div>
              <div className="format-check-list generated-file-list">{generatedExtensions.map((extension) => { const checked = outputDraft.allowed_file_extensions.includes(extension); return <label key={extension} title={`允许容器接收原始 ${extension} 文件`} className={`check-field compact-check ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={(event) => setOutputDraft((current) => ({ ...current, allowed_file_extensions: event.target.checked ? [...current.allowed_file_extensions, extension] : current.allowed_file_extensions.filter((item) => item !== extension) }))} /><span>{extension}</span></label> })}</div>
              <Field label="JSON 文件模式" hint="full 保留容器记录；content 只导出正文/结构化 content"><select value={outputDraft.json_mode} disabled={!outputDraft.export_formats.includes('json')} onChange={(event) => setOutputDraft((current) => ({ ...current, json_mode: event.target.value as 'content' | 'full' }))}><option value="full">完整记录</option><option value="content">仅内容</option></select></Field>
              <div className="managed-output-card"><span className="field-caption">MANAGED OUTPUT LAYOUT</span><strong>默认位置（只读）</strong><code>data/runs/&lt;run_id&gt;/workspace/exports/&lt;flatid&gt;/</code><code>data/runs/&lt;run_id&gt;/workspace/output-manifest.json</code><small><b>result.txt / result.md</b>：正文副本；<b>result.json</b>：按 JSON 模式导出完整记录或仅内容；<b>files/</b>：Agent 在 outputs/ 中真实生成并通过扩展名过滤的文件；<b>provenance.json</b>：本次输入、模型、提示词与技能快照，用于追溯；<b>export-receipt.json</b>：完成标记与文件哈希，用于防止重复覆盖；<b>output-manifest.json</b>：运行级索引与下载路径。后 3 项是必需内部记录，不能关闭。data/outputs 只会按现有运行约定创建，不是当前导出目的地；设置页也不会授予路径。</small></div>
              <div className="settings-actions"><button className="run-button" type="button" onClick={() => void saveOutputDefaults()} disabled={busy === 'output-defaults-save'}><Save size={14} />保存输出默认值</button></div>
            </div>
            <div className="settings-list-card settings-default-policy">
              <div className="settings-card-heading"><div><span className="field-caption">OPTIONAL REFRESH POLICY</span><strong>检查策略</strong></div><span className="settings-count">runtime / SkillHub</span></div>
              <label className="check-field"><input type="checkbox" checked={agentCheckOnSettingsOpen} onChange={(event) => { void onSetAgentCheckOnSettingsOpen(event.target.checked).then(() => setFeedback(event.target.checked ? '已开启：以后打开设置时会执行一次有界只读检查。' : '已关闭：打开设置不再自动检查 Agent。')).catch((error) => setFeedback(`保存检查偏好失败：${error instanceof Error ? error.message : String(error)}`)) }} /><span>打开全局设置时自动检查并刷新 Agent</span><small>只读版本/模型/effort 与已确认的登录状态；不会登录、登出、浏览器授权、刷新凭据或运行推理。</small></label>
              <label className="check-field"><input type="checkbox" checked={autoCheckMounts} onChange={(event) => { void onSetAutoCheckMounts(event.target.checked).then(() => setFeedback(event.target.checked ? '已开启：分析器挂载或切换 Agent 时自动检查当前 Skill。' : '已关闭自动检查；仍可在分析器检查器中手动检查。')).catch((error) => setFeedback(`保存 Skill 检查偏好失败：${error instanceof Error ? error.message : String(error)}`)) }} /><span>挂载 Skill 后自动做静态依赖检查</span><small>只检查当前节点、Agent 和所选 Skill；不启动 Skill/MCP，不执行脚本，不调用模型。</small></label>
              <div className="settings-subsection dependency-cache-settings">
                <div className="settings-card-heading"><div><span className="field-caption">PERSISTENT CHECK CACHE</span><strong>依赖检查缓存</strong></div><span className="settings-count">{dependencyCache.length} 条</span></div>
                <div className="settings-actions"><button className="outline-button" type="button" onClick={() => void loadDependencyCache()} disabled={busy === 'dependency-cache'}><RefreshCw size={13} className={busy === 'dependency-cache' ? 'spin' : ''} />查看记录</button><button className="outline-button" type="button" onClick={() => void clearDependencyCache()} disabled={busy === 'dependency-cache-clear'}><Trash2 size={13} />清理缓存</button></div>
                {dependencyCache.length > 0 && <div className="dependency-cache-list">{dependencyCache.slice(0, 12).map((item) => <div className="dependency-cache-row" key={item.cache_key || `${item.skill_id}-${item.checked_at}`}><span><strong>{item.skill_id}</strong><small>{item.agent_id || 'Agent'} · {item.status} · {item.cache_hit ? '命中' : '检查'} · {item.checked_at ? new Date(item.checked_at).toLocaleString() : '时间未知'}</small></span><span className={`cache-state ${item.invalidation_reason ? 'stale' : ''}`}>{item.invalidation_reason || (item.expires_at && new Date(item.expires_at) > new Date() ? '有效' : '已过期')}</span></div>)}</div>}
                <small>只保存 Skill/依赖声明/Agent runtime 的无密钥指纹、结果和时间；不会写入 API key、完整环境或原始 Skill 输出。</small>
              </div>
            </div>
          </div>}
          {tab === 'appearance' && <div className="settings-editor-card appearance-settings-modal">
            <div className="settings-card-heading"><div><span className="field-caption">VISUAL SYSTEM</span><strong>外观与可读性</strong></div></div>
            <p className="helper-copy">设置会应用到画布、节点卡片、编辑器与全局面板；只在点击保存后成为下次打开的默认样式。</p>
            <div className="appearance-preview" style={{ backgroundColor: appearance.canvas, backgroundImage: backgroundUrl ? `linear-gradient(rgba(255,255,255,.35), rgba(255,255,255,.35)), url(${backgroundUrl})` : undefined }}><div className="appearance-preview-heading" style={{ fontFamily: appearance.text_font || undefined }}>Aa 研究画布</div><div className="appearance-preview-body" style={{ fontFamily: appearance.text_font || undefined, fontSize: `${appearance.font_size}px` }}>本机字体与字号会实时应用到文本控件。</div><code style={{ fontFamily: appearance.code_font || undefined, fontSize: `${appearance.code_font_size}px` }}>route: "evidence"</code></div>
            <datalist id="kxy-font-list">{fonts.map((font) => <option key={font.family} value={font.family}>{font.monospace ? '等宽' : '文本'}</option>)}</datalist>
            <div className="palette-row"><button className={appearance.palette === 'paper' ? 'palette-choice selected paper-choice' : 'palette-choice paper-choice'} onClick={() => onAppearance({ palette: 'paper', canvas: '#faf8f5' })}>纸张</button><button className={appearance.palette === 'sage' ? 'palette-choice selected sage-choice' : 'palette-choice sage-choice'} onClick={() => onAppearance({ palette: 'sage', canvas: '#f7faf5' })}>鼠尾草</button><button className={appearance.palette === 'mist' ? 'palette-choice selected mist-choice' : 'palette-choice mist-choice'} onClick={() => onAppearance({ palette: 'mist', canvas: '#f5f8fb' })}>雾蓝</button></div>
            <div className="two-fields"><Field label="强调色"><input aria-label="强调色" type="color" value={appearance.accent} onChange={(event) => onAppearance({ accent: event.target.value })} /></Field><Field label="画布底色"><input aria-label="画布底色" type="color" value={appearance.canvas} onChange={(event) => onAppearance({ canvas: event.target.value })} /></Field></div>
            <Field label="字体预设"><select value={appearance.font} onChange={(event) => onAppearance({ font: event.target.value as Appearance['font'] })}><option value="system">系统无衬线</option><option value="serif">编辑感衬线</option><option value="mono">等宽工作台</option></select></Field>
            <div className="two-fields"><Field label="文本字体（本机可搜索）" hint="只使用已安装字体，不上传字体文件"><input list="kxy-font-list" aria-label="文本字体" value={appearance.text_font || appearance.custom_font} onChange={(event) => onAppearance({ text_font: event.target.value, custom_font: event.target.value })} placeholder={fonts.length ? '搜索本机字体' : '字体发现不可用，使用系统回退'} /></Field><Field label="代码字体（本机可搜索）" hint="编辑器与代码预览独立使用"><input list="kxy-font-list" aria-label="代码字体" value={appearance.code_font} onChange={(event) => onAppearance({ code_font: event.target.value })} placeholder="如 SF Mono" /></Field></div>
            <div className="two-fields"><Field label="文本字号（px）"><input aria-label="文本字号" type="number" min={12} max={22} value={appearance.font_size} onChange={(event) => onAppearance({ font_size: Math.max(12, Math.min(22, Number(event.target.value) || 14)) })} /></Field><Field label="代码字号（px）"><input aria-label="代码字号" type="number" min={10} max={22} value={appearance.code_font_size} onChange={(event) => onAppearance({ code_font_size: Math.max(10, Math.min(22, Number(event.target.value) || 13)) })} /></Field></div>
            <div className="appearance-media-row"><div className="appearance-background-preview" style={{ backgroundColor: appearance.canvas, backgroundImage: backgroundUrl ? `url(${backgroundUrl})` : undefined }}><ImagePlus size={16} />{backgroundUrl ? '已设置背景图' : '无背景图'}</div><div className="settings-actions"><input ref={backgroundInputRef} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUploadBackground(file); event.target.value = '' }} /><button className="outline-button" type="button" onClick={() => backgroundInputRef.current?.click()}><ImagePlus size={14} />上传背景图</button><button className="outline-button" type="button" onClick={onClearBackground} disabled={!appearance.background_image}><Eraser size={14} />清除背景图</button></div></div>
            <div className="appearance-options"><label className="check-field"><input type="checkbox" checked={appearance.motion_enabled} onChange={(event) => onAppearance({ motion_enabled: event.target.checked })} /><span>启用画布点动效</span><small>关闭后不运行网格帧循环；系统减弱动态效果仍优先。</small></label><Field label="撤回步数（会话内）" hint="只保存深度偏好，不保存图编辑历史"><input aria-label="撤回步数" type="number" min={1} max={50} value={appearance.undo_limit} onChange={(event) => onAppearance({ undo_limit: Math.max(1, Math.min(50, Number(event.target.value) || 5)) })} /></Field><Field label={`点动效强度（0–500，当前 ${appearance.motion_intensity}）`} hint="30为标准强度，100为旧上限，500为本次上限；只提高颜色对比，颜色达到最深后不再加深，0关闭高亮。"><input aria-label="点动效强度" aria-valuetext={`${appearance.motion_intensity}`} type="range" min={0} max={500} step={1} value={appearance.motion_intensity} onChange={(event) => onAppearance({ motion_intensity: Math.max(0, Math.min(500, Number(event.target.value))) })} /></Field></div>
            <div className="settings-actions"><button className="outline-button" onClick={onResetAppearance}>恢复默认</button><button className="run-button" onClick={onSaveAppearance}><Save size={14} />保存为默认样式</button></div>
          </div>}
        </div>
      </section>
    </div>
  )
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="form-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

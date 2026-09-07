export type Role = 'participant' | 'methodist' | 'admin'
export type AvatarProfile = 'legacy_3d' | 'tavus_sergei' | 'anam_tatiana'
export type Presentation = { revision: number; voice_mode: 'text' | 'avatar'; avatar_profile: AvatarProfile; allow_audio_fallback: boolean }
export type Stage = { id: string; title: string; objective: string; opening_line?: string }
export type Criterion = { id: string; title: string; description: string; weight: number }
export type Scenario = {
  id: string; revision: number; title: string; category: string; description: string; situation?: string
  employee_role: string; npc_name: string; npc_role: string; manner?: string; context?: string
  boundaries?: string; duration_minutes: number; stages: Stage[]; criteria: Criterion[]
  status: 'draft' | 'published' | 'archived'; updated_at?: string
}
export type Settings = {
  revision: number; provider: 'openai' | 'demo'; model: 'gpt-5.6-luna' | 'gpt-4.1-mini-2025-04-14'
  mode: 'practice' | 'assessment'; difficulty: 'supportive' | 'balanced' | 'strict'
  max_turns: number; voice_mode: 'text' | 'avatar'; instructions: string
  avatar_profile?: AvatarProfile; allow_audio_fallback?: boolean
}
export type Grade = {
  criterion_id: string; score: number | null; comment: string
  evidence: { turn_id: string; quote: string }[]; recommendation: string
}
export type Report = {
  summary: string; criteria: Grade[]; strengths: string[]; next_steps: string[]
  overall_score: number | null; covered: number; total: number
  source: 'llm' | 'manual_required'; warning: string; created_at: string
}
export type Turn = {
  id: string; request_id: string; user_text: string; reply: string; interrupted?: boolean; stage_index: number
  status: 'pending' | 'committed' | 'cancelled' | 'failed'; created_at: string; elapsed_ms: number | null
}
export type Session = {
  id: string; participant: string; scenario: Scenario; stage_index: number; status: 'active' | 'completed'
  turns: Turn[]; report: Report | null; report_status: 'none' | 'pending' | 'ready' | 'failed'; report_error: string
  completion_reason: string; review_note: string; reviewed: boolean; created_at: string
  mode: 'practice' | 'assessment'; is_demo: boolean; max_turns: number; voice_mode?: 'text' | 'avatar'; opening_message: string
  avatar_profile?: AvatarProfile; allow_audio_fallback?: boolean
  voice_metrics?: { kind: string; ms: number; profile: string; audio_only: boolean }[]
  progress_mode?: 'ordered' | 'flexible'
  stage_progress?: { stage_id: string; quote: string; turn_id: string }[]
}
export type SessionCard = {
  id: string; title: string; participant: string; status: string; created_at: string; score: number | null
  reviewed: boolean; report_status: string; is_demo: boolean; turns: number
  covered: number; total: number
}
export type Bootstrap = {
  scenarios: Scenario[]; sessions: SessionCard[]
  runtime: { external_processing: boolean; is_demo: boolean; mode: string; voice_mode?: string; asr?: { available: boolean; engine: string; model: string; local_only: boolean } }
  settings?: Settings
  presentation?: Presentation
  avatar_profiles?: { id: AvatarProfile; title: string; description: string; provider: string }[]
  avatar_status?: Record<string, { available: boolean; detail: string }>
  budget?: {
    available: boolean; key_configured: boolean; enabled: boolean; unlimited?: boolean
    max_requests: number | null; used_requests: number; remaining_requests: number | null
    usage?: {
      input_tokens: number; output_tokens: number; total_tokens: number; cached_tokens: number
      cache_write_tokens: number; reasoning_tokens: number; measured_requests: number; unmeasured_requests: number
      priced_requests: number; unpriced_requests: number; estimated_cost_usd: number | null
      price_version: string; price_sources: string[]; first_measured_at: string | null
      recent: { operation: string; created_at: string; model: string | null; state: string; total_tokens: number | null; estimated_cost_usd: number | null }[]
    }
  }
}

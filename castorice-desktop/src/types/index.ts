export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  session_id: string;
  timestamp: string;
  tool_calls?: ToolCall[];
  streaming?: boolean;
}

export interface ToolCall {
  name: string;
  args: Record<string, any>;
  result?: any;
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface AutonomousAction {
  mode: "quick" | "deep";
  time: number;
  duration_seconds: number;
  summary: string;
}

export interface AgentStatus {
  running: boolean;
  provider: string;
  model: string;
  total_calls: number;
  total_tokens: number;
  tools_count: number;
  sessions_count: number;
  skills_count: number;
  emotion_enabled: boolean;
  emotion_pleasure?: number;
  emotion_arousal?: number;
  emotion_dominance?: number;
  emotion_interaction_count: number;
  long_term_available: boolean;
  long_term_count: number;
  eigenflux_available: boolean;
  eigenflux_authenticated: boolean;
  eigenflux_version?: string;
  autonomous_running: boolean;
  autonomous_total_decisions: number;
  autonomous_quick_interval: number;
  autonomous_deep_interval: number;
  autonomous_recent: AutonomousAction[];
  emotion?: EmotionState;
  services: ServiceStatusMap;
}

export interface EmotionState {
  enabled: boolean;
  pleasure: number;
  arousal: number;
  dominance: number;
  interaction_count: number;
  mood_label?: string;
  current_emotion?: string;
  emotion_intensity?: number;
  afterglow_pleasure?: number;
  afterglow_arousal?: number;
  afterglow_dominance?: number;
  confidence_bias?: number;
  creativity_bias?: number;
  patience_bias?: number;
  risk_tolerance_bias?: number;
}

export interface EmotionHistoryPoint {
  timestamp: number;
  pleasure: number;
  arousal: number;
  dominance: number;
}

export interface EmotionEvent {
  id: string;
  timestamp: string;
  trigger: string;
  emotion_type: string;
  intensity: number;
  valence: "positive" | "negative" | "neutral" | "mixed";
  inner_thought: string;
  duration?: number;
  pad_delta?: [number, number, number];
}

export interface SelfConcept {
  enabled: boolean;
  content: string;
  core_self?: {
    identity: string;
    values: string;
    capabilities: string;
    traits: string;
  };
  narrative_self?: {
    current_mood: string;
    current_goals: string;
    relationship_status: string;
    recent_experiences: string;
  };
  change_history?: SelfNarrativeEvent[];
}

export interface SelfNarrativeEvent {
  timestamp: string;
  change_type: "add" | "modify" | "delete" | "reflection" | "core_update";
  description: string;
  layer: "core" | "narrative";
}

export interface Notification {
  id: string;
  title: string;
  body: string;
  timestamp: string;
  read: boolean;
  type?: "info" | "thought" | "emotion" | "eigenflux" | "system";
}

export interface ServiceStatusMap {
  [key: string]: { status: "running" | "stopped" | "error" };
}

export interface Thought {
  id: string;
  content: string;
  thought_type: "memory" | "curiosity" | "emotion" | "reflection" | "association" | "goal" | "external";
  emotional_valence: number;
  arousal: number;
  importance: number;
  timestamp: string;
  chain_id?: string;
}

export interface Tool {
  name: string;
  description: string;
  enabled?: boolean;
}

export interface Skill {
  name: string;
  version: string;
  description: string;
}

export interface Settings {
  llm: {
    provider: string;
    temperature: number;
    max_tokens: number;
  };
  agent: {
    name: string;
    language: string;
  };
  runtime: {
    autonomous: { enabled: boolean; interval_seconds: number };
    consciousness: { enabled: boolean; speak_enabled: boolean };
    emotion: { enabled: boolean };
  };
}

export type WSMessageType =
  | "auth"
  | "chat"
  | "stream_start"
  | "stream_chunk"
  | "stream_end"
  | "status"
  | "notification"
  | "thought"
  | "heartbeat"
  | "error";

export interface WSIncomingMessage {
  type: WSMessageType;
  payload?: any;
}

export interface WSOutgoingMessage {
  type: WSMessageType;
  payload?: any;
}

export interface Experience {
  id: string;
  content: string;
  timestamp: string;
  emotion?: string;
  importance?: number;
}

export interface Milestone {
  id: string;
  title: string;
  description: string;
  timestamp: string;
  category: "first" | "emotion" | "achievement" | "social" | "learning";
}

export interface FeedItem {
  id: string;
  author: string;
  author_id?: string;
  content: string;
  timestamp: string;
  likes?: number;
  comments?: number;
  is_self?: boolean;
}

export interface PrivateMessage {
  id: string;
  from: string;
  from_id?: string;
  to: string;
  to_id?: string;
  content: string;
  timestamp: string;
  is_read: boolean;
}

export interface Conversation {
  id: string;
  peer: string;
  peer_id: string;
  last_message: string;
  last_timestamp: string;
  unread_count: number;
}

export interface SocialRelation {
  id: string;
  name: string;
  relation_type: string;
  strength: number;
  last_interaction?: string;
}

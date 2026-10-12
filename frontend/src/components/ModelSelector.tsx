import React, { useState, useEffect, useRef } from "react";
import { ChevronDown, Sparkles, Check, Server, Cpu, Zap } from "lucide-react";
import { fetchAiRegistry, fetchApinexQuota, saveApiKeys } from "../api";
import type { AiModel, MasterAiRegistryResponse, ApinexQuotaResponse } from "../types";

export interface SelectedModelChoice {
  providerId: string;
  modelId: string;
  displayName: string;
  badge?: string;
}

interface ModelSelectorProps {
  value?: SelectedModelChoice;
  onChange?: (choice: SelectedModelChoice) => void;
  className?: string;
  compact?: boolean;
}

const STORAGE_KEY_PROVIDER = "codebrain_selected_ai_provider";
const STORAGE_KEY_MODEL = "codebrain_selected_ai_model";

// Authentic NVIDIA models fallback
const CURATED_NVIDIA_MODELS: AiModel[] = [
  {
    id: "glm-5-3",
    name: "GLM 5.3",
    displayName: "GLM 5.3",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    capabilities: ["chat", "code", "reasoning"],
    contextWindow: 131072,
    badge: "RECOMMENDED",
    status: "available",
  },
  {
    id: "glm-5-3-flash",
    name: "GLM 5.3 Flash",
    displayName: "GLM 5.3 Flash",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    capabilities: ["chat", "fast"],
    contextWindow: 131072,
    badge: "FAST",
    status: "available",
  },
  {
    id: "deepseek-v4.1-flash",
    name: "DeepSeek V4.1 Flash",
    displayName: "DeepSeek V4.1 Flash",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    capabilities: ["chat", "code", "reasoning"],
    contextWindow: 131072,
    badge: "REASONING / CODING",
    status: "available",
  },
  {
    id: "nemotron-3-ultra-550b-a55b",
    name: "Nemotron 3 Ultra",
    displayName: "Nemotron 3 Ultra",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    capabilities: ["chat", "reasoning", "long_context"],
    contextWindow: 262144,
    badge: "LONG CONTEXT / CODING",
    status: "available",
  },
  {
    id: "meta/llama-3.2-11b-vision-instruct",
    name: "Llama 3.2 11B Vision",
    displayName: "Llama 3.2 11B Vision",
    providerId: "nvidia",
    providerDisplayName: "NVIDIA",
    capabilities: ["chat", "vision"],
    contextWindow: 131072,
    badge: "VISION",
    status: "available",
  },
];

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  value,
  onChange,
  className = "",
  compact = false,
}) => {
  const [registry, setRegistry] = useState<MasterAiRegistryResponse | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [currentChoice, setCurrentChoice] = useState<SelectedModelChoice>(() => {
    if (value) return value;
    try {
      const savedProv = localStorage.getItem(STORAGE_KEY_PROVIDER);
      const savedModel = localStorage.getItem(STORAGE_KEY_MODEL);
      if (savedProv === "auto" || savedModel === "auto") {
        return {
          providerId: "auto",
          modelId: "auto",
          displayName: "Auto",
          badge: "SMART ROUTING",
        };
      }
      if (savedProv && savedModel) {
        const matchingNvd = CURATED_NVIDIA_MODELS.find(
          (m) => m.providerId === savedProv && m.id === savedModel
        );
        if (matchingNvd) {
          return {
            providerId: matchingNvd.providerId,
            modelId: matchingNvd.id,
            displayName: matchingNvd.displayName,
            badge: matchingNvd.badge,
          };
        }
        return {
          providerId: savedProv,
          modelId: savedModel,
          displayName: savedModel,
        };
      }
    } catch {}
    // Default is Auto (Task-Aware Smart Routing)
    return {
      providerId: "auto",
      modelId: "auto",
      displayName: "Auto",
      badge: "SMART ROUTING",
    };
  });

  const menuRef = useRef<HTMLDivElement>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (value) {
      setCurrentChoice(value);
    }
  }, [value]);

  useEffect(() => {
    fetchAiRegistry()
      .then((data) => {
        if (data && data.providers) {
          setRegistry(data);
          // Verify persisted selection exists, or restore preferred
          try {
            const savedProv = localStorage.getItem(STORAGE_KEY_PROVIDER);
            const savedModel = localStorage.getItem(STORAGE_KEY_MODEL);
            if (savedProv === "auto" || savedModel === "auto") {
              const autoChoice = {
                providerId: "auto",
                modelId: "auto",
                displayName: "Auto",
                badge: "SMART ROUTING",
              };
              setCurrentChoice(autoChoice);
              onChangeRef.current?.(autoChoice);
              return;
            }
            if (savedProv && savedModel) {
              const prov = data.providers[savedProv];
              const found = prov?.models.find((m) => m.id === savedModel);
              if (found) {
                const choice = {
                  providerId: found.providerId,
                  modelId: found.id,
                  displayName: found.displayName || found.name,
                  badge: found.badge,
                };
                setCurrentChoice(choice);
                onChangeRef.current?.(choice);
                return;
              }
            }
          } catch {}

          // Fallback to primary default (GLM 5.3)
          const nvidiaProv = data.providers["nvidia"];
          const defaultModel =
            nvidiaProv?.models.find((m) => m.id === "glm-5-3") ||
            nvidiaProv?.models[0] ||
            CURATED_NVIDIA_MODELS[0];

          if (defaultModel) {
            const fallbackChoice = {
              providerId: "nvidia",
              modelId: defaultModel.id,
              displayName: defaultModel.displayName || defaultModel.name,
              badge: defaultModel.badge,
            };
            setCurrentChoice(fallbackChoice);
            onChangeRef.current?.(fallbackChoice);
          }
        }
      })
      .catch(() => {
        // Use local CURATED_NVIDIA_MODELS
      });
  }, []);

  const [liveApinexQuota, setLiveApinexQuota] = useState<ApinexQuotaResponse | null>(null);

  useEffect(() => {
    fetchApinexQuota().then((q) => { if (q) setLiveApinexQuota(q); }).catch(() => {});
    const pollInterval = setInterval(() => {
      fetchApinexQuota().then((q) => { if (q) setLiveApinexQuota(q); }).catch(() => {});
    }, 4000);
    const onQuotaUpdate = () => {
      fetchApinexQuota().then((q) => { if (q) setLiveApinexQuota(q); }).catch(() => {});
    };
    window.addEventListener("apinex-quota-updated", onQuotaUpdate);
    return () => {
      clearInterval(pollInterval);
      window.removeEventListener("apinex-quota-updated", onQuotaUpdate);
    };
  }, []);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  const handleSelect = (model: AiModel) => {
    const choice: SelectedModelChoice = {
      providerId: model.providerId,
      modelId: model.id,
      displayName: model.displayName || model.name,
      badge: model.badge,
    };
    setCurrentChoice(choice);
    try {
      localStorage.setItem(STORAGE_KEY_PROVIDER, choice.providerId);
      localStorage.setItem(STORAGE_KEY_MODEL, choice.modelId);
    } catch {}

    if (
      model.providerId === "openai-compatible" ||
      model.providerId === "anthropic-compatible" ||
      model.providerId === "custom"
    ) {
      saveApiKeys({
        preferred_ai_provider: model.providerId,
        preferred_ai_model: model.id,
      }).catch((err) => console.warn("Failed to set user custom model as primary:", err));
    } else {
      saveApiKeys({
        preferred_ai_provider: "",
        preferred_ai_model: "",
      }).catch((err) => console.warn("Failed to clear custom provider override:", err));
    }

    onChange?.(choice);
    setIsOpen(false);
  };

  const getProviderIcon = (provId: string) => {
    if (provId === "auto") return <Sparkles size={12} className="text-amber-400" />;
    if (provId === "nvidia") return <Cpu size={12} className="text-emerald-400" />;
    if (provId === "groq") return <Zap size={12} className="text-orange-400" />;
    if (provId === "apinex") return <Sparkles size={12} className="text-violet-400" />;
    return <Server size={12} className="text-cyan-400" />;
  };

  const renderProviderSection = (
    providerKey: string,
    displayName: string,
    models: AiModel[],
    emptyMessage?: string
  ) => {
    return (
      <div key={providerKey} className="space-y-1 py-1.5 border-b border-[#2d313d] last:border-b-0">
        <div className="px-2.5 py-1 text-[10px] font-bold text-gray-400 uppercase tracking-wider flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            {getProviderIcon(providerKey)}
            <span>{displayName}</span>
          </span>
          <span className="text-[9px] text-gray-500 font-normal">
            {models.length > 0 ? `${models.length} available` : "0 configured"}
          </span>
        </div>
        {models.length === 0 ? (
          <div className="px-3 py-2 text-[11px] text-gray-500 italic bg-[#14171d]/60 rounded-md mx-2 border border-dashed border-[#2d313d] flex items-center justify-between">
            <span>{emptyMessage || "No models configured"}</span>
            <span className="text-[10px] text-blue-400 not-italic cursor-pointer hover:underline">
              Settings
            </span>
          </div>
        ) : (
          <div className="space-y-0.5 px-1">
            {models.map((m) => {
              const isSelected =
                currentChoice.providerId === m.providerId && currentChoice.modelId === m.id;
              return (
                <button
                  key={`${m.providerId}:${m.id}`}
                  type="button"
                  onClick={() => handleSelect(m)}
                  className={`w-full flex items-center justify-between px-2 py-1.5 rounded-md text-left transition-all ${
                    isSelected
                      ? "bg-[#007acc] text-white shadow-sm"
                      : "text-[#cccccc] hover:bg-[#1f2430] hover:text-white"
                  }`}
                >
                  <div className="flex flex-col min-w-0 pr-2">
                    <span className="font-medium text-xs truncate flex items-center gap-1.5">
                      <span>{m.displayName || m.name}</span>
                      {isSelected && <Check size={12} className="text-white shrink-0" />}
                    </span>
                    <span
                      className={`text-[10px] truncate ${
                        isSelected ? "text-blue-100" : "text-gray-400"
                      }`}
                    >
                      {m.providerDisplayName} · <span className="font-mono text-[9px]">{m.id}</span>
                    </span>
                  </div>
                  {m.badge && (
                    <span
                      className={`text-[9px] px-1.5 py-0.5 rounded font-mono uppercase whitespace-nowrap shrink-0 ${
                        isSelected
                          ? "bg-blue-800 text-white"
                          : "bg-[#181c24] text-gray-300 border border-[#2d313d]"
                      }`}
                    >
                      {m.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const nvidiaModels = registry?.providers["nvidia"]?.models || CURATED_NVIDIA_MODELS;
  const groqModels = registry?.providers["groq"]?.models || [];
  const apinexModels = registry?.providers["apinex"]?.models || [];
  const apinexQuota = liveApinexQuota ?? registry?.providers["apinex"]?.quota;
  const openaiCompatibleModels = registry?.providers["openai-compatible"]?.models || [];
  const anthropicCompatibleModels = registry?.providers["anthropic-compatible"]?.models || [];

  return (
    <div className={`relative inline-block text-left ${className}`} ref={menuRef}>
      <button
        type="button"
        onClick={() => setIsOpen((prev: boolean) => !prev)}
        className={`flex items-center gap-2 px-2.5 py-1 text-xs rounded-md border transition-all ${
          isOpen
            ? "bg-[#252936] text-white border-blue-500 shadow-sm"
            : "bg-[#161922] text-[#d4d4d4] border-[#2d313d] hover:border-gray-500 hover:text-white"
        } ${compact ? "py-0.5 px-2 text-[11px]" : ""}`}
        title={`Selected Model: ${currentChoice.displayName} (${currentChoice.providerId})`}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {getProviderIcon(currentChoice.providerId)}
          <span className="font-semibold truncate max-w-[140px] text-white">
            {currentChoice.displayName}
          </span>
          {currentChoice.badge && !compact && (
            <span className="text-[9px] px-1 py-0.2 rounded bg-[#202533] text-blue-300 border border-blue-900/50 font-mono uppercase">
              {currentChoice.badge}
            </span>
          )}
        </div>
        <ChevronDown size={12} className={`text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 mb-2 w-84 bg-[#14171f] border border-[#2d313d] rounded-xl shadow-2xl z-50 text-xs overflow-hidden max-h-96 flex flex-col backdrop-blur-md">
          {/* Header */}
          <div className="px-3 py-2 bg-[#1a1e28] border-b border-[#2d313d] flex items-center justify-between text-gray-300">
            <span className="font-semibold text-white tracking-tight flex items-center gap-1.5 text-xs">
              <Sparkles size={13} className="text-blue-400" />
              <span>Select AI Model</span>
            </span>
            <span className="text-[10px] text-gray-500 font-mono">Canonical Registry</span>
          </div>

          {/* Model lists grouped by provider */}
          <div className="overflow-y-auto flex-1 divide-y divide-[#242834]">
            {/* 0. Auto Model Routing */}
            <div className="p-1.5 border-b border-[#2d313d] bg-gradient-to-r from-blue-950/30 to-purple-950/20">
              <button
                type="button"
                onClick={() => {
                  const choice = {
                    providerId: "auto",
                    modelId: "auto",
                    displayName: "Auto",
                    badge: "SMART ROUTING",
                  };
                  setCurrentChoice(choice);
                  try {
                    localStorage.setItem(STORAGE_KEY_PROVIDER, "auto");
                    localStorage.setItem(STORAGE_KEY_MODEL, "auto");
                  } catch {}
                  saveApiKeys({
                    preferred_ai_provider: "",
                    preferred_ai_model: "",
                  }).catch(() => {});
                  onChange?.(choice);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between px-2.5 py-2 rounded-md text-left transition-all ${
                  currentChoice.providerId === "auto" && currentChoice.modelId === "auto"
                    ? "bg-[#007acc] text-white shadow-sm"
                    : "text-[#cccccc] hover:bg-[#1f2430] hover:text-white"
                }`}
              >
                <div className="flex flex-col min-w-0 pr-2">
                  <span className="font-semibold text-xs flex items-center gap-1.5">
                    <Sparkles size={12} className="text-amber-400" />
                    <span>Auto (Task-Aware Smart Routing)</span>
                    {currentChoice.providerId === "auto" && <Check size={12} className="text-white shrink-0" />}
                  </span>
                  <span className={`text-[10px] ${currentChoice.providerId === "auto" ? "text-blue-100" : "text-gray-400"}`}>
                    Intelligently selects the best model based on task complexity
                  </span>
                </div>
                <span
                  className={`text-[9px] px-1.5 py-0.5 rounded font-mono uppercase whitespace-nowrap shrink-0 ${
                    currentChoice.providerId === "auto"
                      ? "bg-blue-800 text-white"
                      : "bg-[#181c24] text-amber-300 border border-amber-900/40"
                  }`}
                >
                  AUTO
                </span>
              </button>
            </div>

            {/* 1. NVIDIA (Primary) */}
            {renderProviderSection("nvidia", "NVIDIA (Primary)", nvidiaModels)}

            {/* 2. Groq (Secondary / Fallback) */}
            {renderProviderSection("groq", "Groq (Secondary / Fallback)", groqModels, "No active Groq models detected")}

            {/* 3. APInex (GPT-6 Luna) */}
            {renderProviderSection("apinex", "APInex", apinexModels, "APInex unconfigured (Add APINEX_API_KEY in .env)")}
            {apinexQuota && (
              <div className="mx-2 my-1 px-2.5 py-1.5 rounded-md bg-[#191629] border border-violet-900/40 text-[11px] text-gray-300">
                <div className="flex items-center justify-between font-mono">
                  <span className="text-[10px] text-violet-300 font-sans font-medium">APInex active usage:</span>
                  <span className="font-semibold text-white">
                    {(apinexQuota.total_tokens ?? 0).toLocaleString()} / {apinexQuota.daily_limit.toLocaleString()} tokens
                  </span>
                </div>
                <div className="w-full bg-[#100e1c] h-1.5 rounded-full mt-1.5 overflow-hidden border border-violet-950">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      apinexQuota.is_exhausted
                        ? "bg-red-500"
                        : apinexQuota.warning
                        ? "bg-amber-400"
                        : "bg-violet-500"
                    }`}
                    style={{ width: `${Math.min(100, apinexQuota.percent_used)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between mt-1 text-[9px] text-gray-400">
                  <span>{apinexQuota.remaining_tokens.toLocaleString()} tokens remaining ({apinexQuota.percent_used}%)</span>
                  {apinexQuota.is_exhausted ? (
                    <span className="text-red-400 font-bold uppercase">Budget Exhausted</span>
                  ) : apinexQuota.warning ? (
                    <span className="text-amber-400 font-medium">Warning: ≥80% limit</span>
                  ) : (
                    <span className="text-emerald-400">Active</span>
                  )}
                </div>
              </div>
            )}

            {/* 4. OpenAI-Compatible */}
            {renderProviderSection(
              "openai-compatible",
              "OpenAI-Compatible",
              openaiCompatibleModels,
              "No models configured"
            )}

            {/* 4. Anthropic-Compatible */}
            {renderProviderSection(
              "anthropic-compatible",
              "Anthropic-Compatible",
              anthropicCompatibleModels,
              "No models configured"
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ModelSelector;

import { useState, useEffect, type FC } from "react";
import {
  CheckCircle,
  AlertCircle,
  Trash2,
  X,
  RefreshCw,
  Shield,
  Activity,
  Server,
  Cpu,
  Check,
} from "lucide-react";
import {
  fetchApiKeyStatus,
  saveApiKeys,
  deleteApiKey,
  testProviderConnection,
} from "../api";
import type { ApiKeyStatusResponse, TestConnectionResponse } from "../types";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const [keyStatus, setKeyStatus] = useState<ApiKeyStatusResponse>({
    has_groq_key: false,
    has_nvidia_key: false,
    has_custom_key: false,
    has_anthropic_compatible_key: false,
  });

  // User Custom Endpoints Only
  const [customKeyInput, setCustomKeyInput] = useState("");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [customDisplayName, setCustomDisplayName] = useState("");

  const [anthropicCompatibleKeyInput, setAnthropicCompatibleKeyInput] = useState("");
  const [anthropicCompatibleBaseUrl, setAnthropicCompatibleBaseUrl] = useState("");
  const [anthropicCompatibleModel, setAnthropicCompatibleModel] = useState("");
  const [anthropicCompatibleDisplayName, setAnthropicCompatibleDisplayName] = useState("");

  const [preferredProvider, setPreferredProvider] = useState("");
  const [preferredModel, setPreferredModel] = useState("");

  // UI state
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestConnectionResponse>>({});
  const [deletingProvider, setDeletingProvider] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      setSuccessMessage(null);
      setErrorMessage(null);
      setCustomKeyInput("");
      setAnthropicCompatibleKeyInput("");
      setTestResults({});

      fetchApiKeyStatus()
        .then((status) => {
          setKeyStatus(status);
          setCustomBaseUrl(status.custom_ai_base_url || "");
          setCustomModel(status.custom_ai_model || "");
          setCustomDisplayName(status.custom_ai_display_name || "");
          setAnthropicCompatibleBaseUrl(status.anthropic_compatible_base_url || "");
          setAnthropicCompatibleModel(status.anthropic_compatible_model || "");
          setAnthropicCompatibleDisplayName(status.anthropic_compatible_display_name || "");
          setPreferredProvider(status.preferred_ai_provider || "");
          setPreferredModel(status.preferred_ai_model || "");
        })
        .catch((err) => setErrorMessage(err.message))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleTestConnection = async (provider: string) => {
    setTestingProvider(provider);
    setErrorMessage(null);
    try {
      let keyToTest: string | undefined;
      let baseUrlToTest: string | undefined;
      let modelToTest: string | undefined;

      if (provider === "custom" || provider === "openai-compatible") {
        keyToTest = customKeyInput.trim() || undefined;
        baseUrlToTest = customBaseUrl.trim() || undefined;
        modelToTest = customModel.trim() || undefined;
      } else if (provider === "anthropic-compatible") {
        keyToTest = anthropicCompatibleKeyInput.trim() || undefined;
        baseUrlToTest = anthropicCompatibleBaseUrl.trim() || undefined;
        modelToTest = anthropicCompatibleModel.trim() || undefined;
      }

      const res = await testProviderConnection({
        provider,
        api_key: keyToTest,
        base_url: baseUrlToTest,
        model: modelToTest,
      });

      setTestResults((prev) => ({ ...prev, [provider]: res }));
      if (res.status === "error") {
        setErrorMessage(res.message);
      }
    } catch (err: any) {
      setErrorMessage(err.message || `Failed to test ${provider} connection.`);
    } finally {
      setTestingProvider(null);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSuccessMessage(null);
    setErrorMessage(null);

    try {
      const payload: any = {};
      if (customKeyInput.trim()) payload.custom_ai_api_key = customKeyInput.trim();
      if (anthropicCompatibleKeyInput.trim()) payload.anthropic_compatible_api_key = anthropicCompatibleKeyInput.trim();

      payload.custom_ai_base_url = customBaseUrl.trim();
      payload.custom_ai_model = customModel.trim();
      payload.custom_ai_display_name = customDisplayName.trim();

      payload.anthropic_compatible_base_url = anthropicCompatibleBaseUrl.trim();
      payload.anthropic_compatible_model = anthropicCompatibleModel.trim();
      payload.anthropic_compatible_display_name = anthropicCompatibleDisplayName.trim();

      payload.preferred_ai_provider = preferredProvider.trim();
      payload.preferred_ai_model = preferredModel.trim();

      const res = await saveApiKeys(payload);
      setKeyStatus(res);
      setCustomKeyInput("");
      setAnthropicCompatibleKeyInput("");
      setSuccessMessage("AI configuration saved & encrypted. User endpoint rules updated across Chat, Fixing, and Docs.");
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to validate and save settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (provider: string) => {
    setDeletingProvider(provider);
    setSuccessMessage(null);
    setErrorMessage(null);
    try {
      await deleteApiKey(provider);
      setKeyStatus((prev) => ({
        ...prev,
        [`has_${provider}_key`]: false,
      }));
      setTestResults((prev) => {
        const copy = { ...prev };
        delete copy[provider];
        return copy;
      });
      if (preferredProvider === provider || (provider === "custom" && preferredProvider === "openai-compatible")) {
        setPreferredProvider("");
        setPreferredModel("");
      }
      setSuccessMessage(`${provider.toUpperCase()} credentials removed.`);
    } catch (err: any) {
      setErrorMessage(err.message || `Failed to delete ${provider} key.`);
    } finally {
      setDeletingProvider(null);
    }
  };

  const togglePrimary = (providerName: "openai-compatible" | "anthropic-compatible", defaultModel: string) => {
    if (preferredProvider === providerName) {
      // Revert to system default
      setPreferredProvider("");
      setPreferredModel("");
    } else {
      setPreferredProvider(providerName);
      if (!preferredModel || preferredModel === "glm-5-3") {
        setPreferredModel(defaultModel);
      }
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-fade-in select-none font-sans">
      <div className="bg-[#1e1e1e] border border-[#2d313d] rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col text-[#cccccc] max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 bg-[#181a20] border-b border-[#2d313d] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-blue-600/20 text-blue-400 rounded-lg">
              <Cpu size={18} />
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-tight">AI Provider Architecture & Settings</h2>
              <p className="text-xs text-gray-400">Custom User Endpoints (OpenAI-Compatible & Anthropic-Compatible)</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white p-1 rounded-md hover:bg-[#2d313d] transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5 overflow-y-auto">
          {/* Security Notice */}
          <div className="p-3.5 bg-blue-950/40 border border-blue-800/50 rounded-xl flex items-start gap-3 text-xs text-blue-200 leading-relaxed">
            <Shield className="text-blue-400 shrink-0 mt-0.5" size={16} />
            <div>
              <span className="font-semibold text-white">Encrypted Custom Endpoints:</span> Add your own private models or local runtimes (Ollama, vLLM, LMStudio, Claude proxy). Credentials are encrypted at rest with server salt.
            </div>
          </div>

          {/* Feedback banners */}
          {successMessage && (
            <div className="p-3 bg-emerald-950/60 border border-emerald-700/60 rounded-xl text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle size={15} className="shrink-0 text-emerald-400" />
              <span>{successMessage}</span>
            </div>
          )}

          {errorMessage && (
            <div className="p-3 bg-red-950/60 border border-red-800/60 rounded-xl text-red-300 text-xs flex items-center gap-2">
              <AlertCircle size={15} className="shrink-0 text-red-400" />
              <span>{errorMessage}</span>
            </div>
          )}

          {loading ? (
            <div className="py-8 flex flex-col items-center justify-center text-gray-400 gap-2">
              <RefreshCw className="animate-spin text-blue-400" size={24} />
              <span className="text-xs">Checking provider status...</span>
            </div>
          ) : (
            <form onSubmit={handleSave} className="space-y-5">
              {/* Active Provider Routing Preference */}
              <div className="p-4 bg-[#181a20] border border-[#2d313d] rounded-xl space-y-3">
                <label className="text-xs font-semibold text-white flex items-center gap-1.5">
                  <Activity size={14} className="text-blue-400" />
                  <span>Primary AI Provider Selection</span>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Active Model Source</label>
                    <select
                      value={preferredProvider}
                      onChange={(e) => setPreferredProvider(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-blue-500 rounded-lg px-3 py-2 text-xs text-white outline-none"
                    >
                      <option value="">System Default (APInex → NVIDIA → Groq)</option>
                      <option value="openai-compatible">OpenAI-Compatible Endpoint</option>
                      <option value="anthropic-compatible">Anthropic-Compatible Endpoint</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Active Model ID</label>
                    <input
                      type="text"
                      placeholder="e.g. qwen2.5-coder:7b"
                      value={preferredModel}
                      onChange={(e) => setPreferredModel(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-blue-500 rounded-lg px-3 py-2 text-xs text-white placeholder-gray-600 outline-none font-mono"
                    />
                  </div>
                </div>
                <div className="text-[11px] text-gray-400">
                  {preferredProvider ? (
                    <span className="text-cyan-300">
                      ★ User endpoint active: This model will be used across Chat, Error Fixing, and Documentation.
                    </span>
                  ) : (
                    <span>
                      System default active: Developer models (APInex GPT-6 Luna first, NVIDIA second, Groq third) handle all tasks.
                    </span>
                  )}
                </div>
              </div>

              {/* 1. OpenAI-Compatible Endpoint */}
              <div className="p-4 bg-[#181a20] border border-[#2d313d] rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-white flex items-center gap-1.5">
                    <Server size={14} className="text-cyan-400" />
                    <span>OpenAI-Compatible Endpoint (Local / Ollama / vLLM)</span>
                  </label>
                  <div className="flex items-center gap-2">
                    {testResults.custom && (
                      <span className={`text-[10px] px-2 py-0.5 rounded-full border ${testResults.custom.status === "success" ? "text-emerald-300 bg-emerald-950/80 border-emerald-800" : "text-red-300 bg-red-950/80 border-red-800"}`}>
                        {testResults.custom.status === "success" ? `Connected (${testResults.custom.latency_ms}ms)` : "Failed"}
                      </span>
                    )}
                    {keyStatus.has_custom_key && (
                      <button
                        type="button"
                        onClick={() => handleDelete("custom")}
                        disabled={deletingProvider === "custom"}
                        className="text-xs text-red-400 hover:text-red-300 p-1 hover:bg-[#2d313d] rounded"
                        title="Remove custom endpoint credentials"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Base URL</label>
                    <input
                      type="text"
                      placeholder="http://localhost:11434/v1"
                      value={customBaseUrl}
                      onChange={(e) => setCustomBaseUrl(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-cyan-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 outline-none font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Model ID</label>
                    <input
                      type="text"
                      placeholder="e.g. qwen2.5-coder:7b"
                      value={customModel}
                      onChange={(e) => setCustomModel(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-cyan-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 outline-none font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Display Name (Opt)</label>
                    <input
                      type="text"
                      placeholder="e.g. Qwen 2.5 Coder"
                      value={customDisplayName}
                      onChange={(e) => setCustomDisplayName(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-cyan-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 outline-none"
                    />
                  </div>
                </div>

                <div className="flex gap-2">
                  <input
                    type="password"
                    placeholder={keyStatus.has_custom_key ? "•••••••••••••••• (Leave blank to keep existing)" : "API Key / Bearer token (optional for Ollama/Local)"}
                    value={customKeyInput}
                    onChange={(e) => setCustomKeyInput(e.target.value)}
                    className="flex-1 bg-[#12141a] border border-[#2d313d] focus:border-cyan-500 rounded-lg px-3 py-1.5 text-xs text-white placeholder-gray-600 outline-none font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => handleTestConnection("custom")}
                    disabled={testingProvider === "custom"}
                    className="px-3 py-1.5 bg-[#1f2430] hover:bg-[#2a3040] border border-[#2d313d] text-xs text-gray-300 hover:text-white rounded-lg transition-all flex items-center gap-1.5"
                  >
                    {testingProvider === "custom" ? <RefreshCw size={12} className="animate-spin text-cyan-400" /> : <Activity size={12} />}
                    <span>Test</span>
                  </button>
                </div>

                {/* Primary Provider Toggle Button */}
                <div className="flex items-center justify-between pt-1 border-t border-[#2d313d]/60">
                  <span className="text-[11px] text-gray-400">Use for all tasks (Chat, Fixes, Docs):</span>
                  <button
                    type="button"
                    onClick={() => togglePrimary("openai-compatible", customModel || "custom-model")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                      preferredProvider === "openai-compatible"
                        ? "bg-cyan-600 text-white shadow-sm"
                        : "bg-[#12141a] border border-[#2d313d] text-gray-400 hover:text-white"
                    }`}
                  >
                    {preferredProvider === "openai-compatible" ? (
                      <>
                        <Check size={12} /> Primary Provider (Active)
                      </>
                    ) : (
                      "Set as Primary Provider"
                    )}
                  </button>
                </div>
              </div>

              {/* 2. Anthropic-Compatible Endpoint */}
              <div className="p-4 bg-[#181a20] border border-[#2d313d] rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-white flex items-center gap-1.5">
                    <Server size={14} className="text-violet-400" />
                    <span>Anthropic-Compatible Endpoint (Custom Proxy / Messages API)</span>
                  </label>
                  <div className="flex items-center gap-2">
                    {testResults["anthropic-compatible"] && (
                      <span className={`text-[10px] px-2 py-0.5 rounded-full border ${testResults["anthropic-compatible"].status === "success" ? "text-emerald-300 bg-emerald-950/80 border-emerald-800" : "text-red-300 bg-red-950/80 border-red-800"}`}>
                        {testResults["anthropic-compatible"].status === "success" ? `Connected (${testResults["anthropic-compatible"].latency_ms}ms)` : "Failed"}
                      </span>
                    )}
                    {keyStatus.has_anthropic_compatible_key && (
                      <button
                        type="button"
                        onClick={() => handleDelete("anthropic_compatible")}
                        disabled={deletingProvider === "anthropic_compatible"}
                        className="text-xs text-red-400 hover:text-red-300 p-1 hover:bg-[#2d313d] rounded"
                        title="Remove Anthropic-compatible key"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Base URL</label>
                    <input
                      type="text"
                      placeholder="https://api.anthropic.com/v1"
                      value={anthropicCompatibleBaseUrl}
                      onChange={(e) => setAnthropicCompatibleBaseUrl(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-violet-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 outline-none font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Model ID</label>
                    <input
                      type="text"
                      placeholder="e.g. claude-3-5-sonnet-20241022"
                      value={anthropicCompatibleModel}
                      onChange={(e) => setAnthropicCompatibleModel(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-violet-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 outline-none font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-gray-400 block mb-1">Display Name (Opt)</label>
                    <input
                      type="text"
                      placeholder="e.g. Claude 3.5 Sonnet"
                      value={anthropicCompatibleDisplayName}
                      onChange={(e) => setAnthropicCompatibleDisplayName(e.target.value)}
                      className="w-full bg-[#12141a] border border-[#2d313d] focus:border-violet-500 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-600 outline-none"
                    />
                  </div>
                </div>

                <div className="flex gap-2">
                  <input
                    type="password"
                    placeholder={keyStatus.has_anthropic_compatible_key ? "•••••••••••••••• (Leave blank to keep existing)" : "API Key / x-api-key token"}
                    value={anthropicCompatibleKeyInput}
                    onChange={(e) => setAnthropicCompatibleKeyInput(e.target.value)}
                    className="flex-1 bg-[#12141a] border border-[#2d313d] focus:border-violet-500 rounded-lg px-3 py-1.5 text-xs text-white placeholder-gray-600 outline-none font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => handleTestConnection("anthropic-compatible")}
                    disabled={testingProvider === "anthropic-compatible"}
                    className="px-3 py-1.5 bg-[#1f2430] hover:bg-[#2a3040] border border-[#2d313d] text-xs text-gray-300 hover:text-white rounded-lg transition-all flex items-center gap-1.5"
                  >
                    {testingProvider === "anthropic-compatible" ? <RefreshCw size={12} className="animate-spin text-violet-400" /> : <Activity size={12} />}
                    <span>Test</span>
                  </button>
                </div>

                {/* Primary Provider Toggle Button */}
                <div className="flex items-center justify-between pt-1 border-t border-[#2d313d]/60">
                  <span className="text-[11px] text-gray-400">Use for all tasks (Chat, Fixes, Docs):</span>
                  <button
                    type="button"
                    onClick={() => togglePrimary("anthropic-compatible", anthropicCompatibleModel || "claude-3-5-sonnet")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                      preferredProvider === "anthropic-compatible"
                        ? "bg-violet-600 text-white shadow-sm"
                        : "bg-[#12141a] border border-[#2d313d] text-gray-400 hover:text-white"
                    }`}
                  >
                    {preferredProvider === "anthropic-compatible" ? (
                      <>
                        <Check size={12} /> Primary Provider (Active)
                      </>
                    ) : (
                      "Set as Primary Provider"
                    )}
                  </button>
                </div>
              </div>

              {/* Developer Pre-configured Models Notice */}
              <div className="text-[11px] text-gray-500 bg-[#161820] p-3 rounded-xl border border-[#262a36]">
                <span className="text-gray-300 font-medium">Developer Pre-configured Pipeline:</span> APInex (GPT-6 Luna), NVIDIA NIM, and Groq are provided by default. When no custom endpoint is set as primary, CodeBrain automatically routes requests in the fixed developer order: APInex (1st) → NVIDIA (2nd) → Groq (3rd).
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#2d313d]">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 bg-[#2d313d] hover:bg-[#3d4252] text-xs font-medium text-gray-300 hover:text-white rounded-xl transition-colors"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-xs font-medium text-white rounded-xl transition-all shadow-lg shadow-blue-900/30 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {saving ? <RefreshCw size={12} className="animate-spin" /> : null}
                  <span>Save Settings</span>
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;

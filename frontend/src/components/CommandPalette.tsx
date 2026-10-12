import type { FC } from "react";
import { useState, useEffect, useRef } from "react";
import { Command } from "lucide-react";

export interface CommandItem {
  id: string;
  title: string;
  category: string;
  icon: any;
  action: () => void;
  shortcut?: string;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  commands: CommandItem[];
}

const CommandPalette: FC<CommandPaletteProps> = ({ isOpen, onClose, commands }) => {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  const filteredCommands = commands.filter(
    (cmd) =>
      cmd.title.toLowerCase().includes(query.toLowerCase()) ||
      cmd.category.toLowerCase().includes(query.toLowerCase())
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % (filteredCommands.length || 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % (filteredCommands.length || 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
        onClose();
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-start justify-center pt-20 z-50 select-none"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl bg-[#252526] border border-[#3c3c3c] rounded-lg shadow-2xl overflow-hidden flex flex-col animate-in fade-in zoom-in-95 duration-100"
      >
        {/* Input bar */}
        <div className="p-3 border-b border-[#3c3c3c] flex items-center gap-2.5 bg-[#1e1e1e]">
          <Command size={16} className="text-[#007acc] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a command or search actions…"
            className="w-full bg-transparent text-white text-xs placeholder-gray-500 focus:outline-none font-sans"
          />
          <span className="text-[10px] text-gray-500 font-mono bg-[#2d2d2d] px-1.5 py-0.5 rounded border border-[#3c3c3c]">
            ESC
          </span>
        </div>

        {/* Results List */}
        <div className="max-h-72 overflow-y-auto p-1.5 space-y-0.5">
          {filteredCommands.length === 0 ? (
            <div className="p-6 text-center text-xs text-[#858585]">
              No matching commands found.
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const Icon = cmd.icon;
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={cmd.id}
                  onClick={() => {
                    cmd.action();
                    onClose();
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex items-center justify-between px-3 py-2 rounded text-xs cursor-pointer transition-colors ${
                    isSelected
                      ? "bg-[#007acc] text-white"
                      : "text-[#cccccc] hover:bg-[#2a2d2e]"
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Icon size={15} className={isSelected ? "text-white" : "text-[#858585]"} />
                    <span className="font-medium truncate">{cmd.title}</span>
                    <span
                      className={`text-[10px] px-1.5 py-0.2 rounded uppercase font-bold tracking-wider ${
                        isSelected ? "bg-white/20 text-white" : "bg-[#333333] text-gray-400"
                      }`}
                    >
                      {cmd.category}
                    </span>
                  </div>
                  {cmd.shortcut && (
                    <span
                      className={`text-[10px] font-mono ${
                        isSelected ? "text-white/80" : "text-gray-500"
                      }`}
                    >
                      {cmd.shortcut}
                    </span>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;

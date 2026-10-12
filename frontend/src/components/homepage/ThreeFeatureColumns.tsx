import type { FC } from "react";
import { Fig01Codebase, Fig02Issues, Fig03Docs } from "./WireframeFigures";

export const ThreeFeatureColumns: FC = () => {
  return (
    <section id="features" className="w-full py-28 px-6 sm:px-8 border-t border-[#2a2b2e]/60">
      <div className="max-w-7xl mx-auto space-y-16">
        {/* Section Heading & Subtitle */}
        <div className="max-w-4xl space-y-4">
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-[#f3f4f6] leading-tight">
            From codebase complexity to shipping with confidence.
          </h2>
          <p className="text-base sm:text-lg text-[#a1a1aa] leading-relaxed max-w-2xl">
            Everything you need to understand your code, improve its quality, and keep your documentation useful.
          </p>
        </div>

        {/* Three Balanced Editorial Columns with Identical Heights & Baseline Alignment */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 lg:gap-12 items-stretch pt-2">
          {/* Column 1: Codebase Intelligence */}
          <div className="flex flex-col justify-between space-y-6 group">
            <div className="space-y-4">
              <span className="font-mono text-xs uppercase tracking-widest text-[#71717a] block">
                FIG 0.1
              </span>
              <div className="h-52 w-full flex items-center justify-center p-4 bg-[#1b1b1d]/30 rounded-xl border border-[#2a2b2e]/40 transition-transform duration-300 group-hover:scale-[1.02]">
                <Fig01Codebase className="w-full h-full max-h-44 max-w-[280px]" />
              </div>
            </div>

            <div className="space-y-2.5 pt-4 border-t border-[#2a2b2e] flex-1 flex flex-col justify-start">
              <h3 className="text-base font-semibold text-[#f3f4f6] tracking-tight min-h-[1.75rem] flex items-center">
                Understand your codebase
              </h3>
              <p className="text-[14px] text-[#a1a1aa] leading-relaxed">
                Explore repository structure, trace dependencies, and understand how modules work together. Turn unfamiliar code into a system you can navigate with confidence.
              </p>
            </div>
          </div>

          {/* Column 2: Issue Detection & Fixes */}
          <div className="flex flex-col justify-between space-y-6 group">
            <div className="space-y-4">
              <span className="font-mono text-xs uppercase tracking-widest text-[#71717a] block">
                FIG 0.2
              </span>
              <div className="h-52 w-full flex items-center justify-center p-4 bg-[#1b1b1d]/30 rounded-xl border border-[#2a2b2e]/40 transition-transform duration-300 group-hover:scale-[1.02]">
                <Fig02Issues className="w-full h-full max-h-44 max-w-[280px]" />
              </div>
            </div>

            <div className="space-y-2.5 pt-4 border-t border-[#2a2b2e] flex-1 flex flex-col justify-start">
              <h3 className="text-base font-semibold text-[#f3f4f6] tracking-tight min-h-[1.75rem] flex items-center">
                Find issues. Fix with context.
              </h3>
              <p className="text-[14px] text-[#a1a1aa] leading-relaxed">
                Surface actionable code issues, trace their causes to the relevant files, and review AI-generated patches before applying changes.
              </p>
            </div>
          </div>

          {/* Column 3: Documentation Generation */}
          <div className="flex flex-col justify-between space-y-6 group">
            <div className="space-y-4">
              <span className="font-mono text-xs uppercase tracking-widest text-[#71717a] block">
                FIG 0.3
              </span>
              <div className="h-52 w-full flex items-center justify-center p-4 bg-[#1b1b1d]/30 rounded-xl border border-[#2a2b2e]/40 transition-transform duration-300 group-hover:scale-[1.02]">
                <Fig03Docs className="w-full h-full max-h-44 max-w-[280px]" />
              </div>
            </div>

            <div className="space-y-2.5 pt-4 border-t border-[#2a2b2e] flex-1 flex flex-col justify-start">
              <h3 className="text-base font-semibold text-[#f3f4f6] tracking-tight min-h-[1.75rem] flex items-center">
                Documentation that explains the system
              </h3>
              <p className="text-[14px] text-[#a1a1aa] leading-relaxed">
                Generate repository-aware documentation, architecture diagrams, API references, and developer guides grounded in the code that actually exists.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

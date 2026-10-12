import { useState, type FC } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, AlertCircle, GitPullRequest, FileCode } from "lucide-react";

export const BuildReviewShipSection: FC = () => {
  const [selectedItem, setSelectedItem] = useState("CB-2498");

  return (
    <section id="cicd" className="w-full shrink-0 py-28 px-6 sm:px-8 border-t border-[#2a2b2e]/60 relative bg-[#161718]">
      <div className="max-w-7xl mx-auto space-y-16">
        {/* Editorial Heading & Description Row */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          <div className="lg:col-span-7">
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-[#f3f4f6] leading-[1.15]">
              Build, test,<br />and ship with confidence.
            </h2>
          </div>

          <div className="lg:col-span-5 space-y-4 lg:pt-2">
            <p className="text-sm sm:text-base text-[#a1a1aa] leading-relaxed">
              Understand how code changes move through validation and deployment. Use CodeBrain's repository intelligence and CI/CD workflows to investigate failures and improve delivery confidence.
            </p>
            <div>
              <Link
                to="/cicd"
                className="inline-flex items-center gap-1.5 text-xs sm:text-[13px] font-medium text-purple-400 hover:text-purple-300 transition-colors group cursor-pointer"
              >
                <span>Explore CI/CD</span>
                <ArrowRight size={13} className="group-hover:translate-x-1 transition-transform" />
              </Link>
            </div>
          </div>
        </div>

        {/* ── Wide Dark CI/CD Product Visual with Progressive Bottom Fade ── */}
        <div className="relative rounded-2xl border border-[#2a2b2e] bg-[#1b1b1d] shadow-[0_25px_80px_rgba(0,0,0,0.8)] overflow-hidden">
          {/* Fading Container using Webkit/CSS mask-image + bottom overlay */}
          <div className="p-4 sm:p-6 pb-28 [mask-image:linear-gradient(to_bottom,black_60%,transparent_100%)]">
            {/* Top Pipeline Progression Bar: Code Change → Tests passed → Build complete → Review required → Deployment successful */}
            <div className="mb-6 p-3 rounded-xl bg-[#161718] border border-[#2a2b2e] flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2 font-mono text-[11px] font-semibold text-[#f3f4f6]">
                <span className="w-2 h-2 rounded-full bg-purple-400" />
                <span>CI/CD PIPELINE</span>
              </div>

              <div className="flex flex-wrap items-center gap-2 sm:gap-4 font-mono text-[10px] text-[#71717a]">
                <div className="flex items-center gap-1 text-[#f3f4f6]">
                  <GitPullRequest size={12} className="text-purple-400" />
                  <span>Code Change</span>
                  <span className="text-emerald-400 font-bold ml-0.5">✓</span>
                </div>
                <span>→</span>
                <div className="flex items-center gap-1 text-emerald-400 font-semibold">
                  <CheckCircle2 size={12} />
                  <span>Tests passed</span>
                </div>
                <span>→</span>
                <div className="flex items-center gap-1 text-emerald-400 font-semibold">
                  <CheckCircle2 size={12} />
                  <span>Build complete</span>
                </div>
                <span>→</span>
                <div className="flex items-center gap-1 text-amber-400 font-semibold">
                  <AlertCircle size={12} />
                  <span>Review required</span>
                </div>
                <span>→</span>
                <div className="flex items-center gap-1 text-purple-300 font-semibold">
                  <CheckCircle2 size={12} />
                  <span>Deployment successful</span>
                </div>
              </div>
            </div>

            {/* Split Interface: Pipeline Status Rail + YAML Workflow View */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
              {/* Left Column: Pipeline Stages (Col 1-4) with requested exact labels */}
              <div className="lg:col-span-4 space-y-5 text-xs text-[#a1a1aa] border-b lg:border-b-0 lg:border-r border-[#2a2b2e] pb-6 lg:pb-0 lg:pr-6">
                {/* Group 1: Tests Passed (Replaces 'In Review') */}
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#f3f4f6] pb-1">
                    <div className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span>Tests Passed</span>
                    <span className="text-[#71717a] ml-1 font-mono">3</span>
                  </div>

                  {[
                    { id: "CB-2498", title: "Unit & integration suite: 229 passed" },
                    { id: "CB-2380", title: "Deterministic AST index verification" },
                    { id: "CB-2039", title: "Security secret scan & token redaction" },
                  ].map((item) => (
                    <div
                      key={item.id}
                      onClick={() => setSelectedItem(item.id)}
                      className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer transition-colors ${
                        selectedItem === item.id
                          ? "bg-[#202124] text-[#f3f4f6] font-medium border border-[#2a2b2e]"
                          : "hover:bg-[#202124]/60 hover:text-[#f3f4f6]"
                      }`}
                    >
                      <span className="font-mono text-[10px] text-[#71717a] shrink-0 pt-0.5">{item.id}</span>
                      <span className="text-[11px] leading-snug">{item.title}</span>
                    </div>
                  ))}
                </div>

                {/* Group 2: Build Complete (Replaces 'In Progress') */}
                <div className="space-y-1.5 pt-2">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#f3f4f6] pb-1">
                    <div className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span>Build Complete</span>
                    <span className="text-[#71717a] ml-1 font-mono">4</span>
                  </div>

                  {[
                    { id: "CB-2076", title: "Vite client bundle compiled (539ms)" },
                    { id: "CB-2108", title: "FastAPI Python backend validated" },
                    { id: "CB-2143", title: "TypeScript typecheck (0 errors)" },
                    { id: "CB-2187", title: "Docker container image built" },
                  ].map((item) => (
                    <div
                      key={item.id}
                      onClick={() => setSelectedItem(item.id)}
                      className={`flex items-start gap-2.5 p-2 rounded-lg cursor-pointer transition-colors ${
                        selectedItem === item.id
                          ? "bg-[#202124] text-[#f3f4f6] font-medium border border-[#2a2b2e]"
                          : "hover:bg-[#202124]/60 hover:text-[#f3f4f6]"
                      }`}
                    >
                      <span className="font-mono text-[10px] text-[#71717a] shrink-0 pt-0.5">{item.id}</span>
                      <span className="text-[11px] leading-snug">{item.title}</span>
                    </div>
                  ))}
                </div>

                {/* Group 3: Deployment Stages (Illustrative Pipeline) */}
                <div className="space-y-1.5 pt-2">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#a1a1aa] pb-1">
                    <div className="w-2 h-2 rounded-full bg-purple-400" />
                    <span>Deployment Successful</span>
                    <span className="text-[#71717a] ml-1 font-mono">1</span>
                  </div>

                  <div className="flex items-start gap-2.5 p-2 rounded-lg text-[#a1a1aa] bg-[#202124]/40 border border-[#2a2b2e]/60">
                    <span className="font-mono text-[10px] text-purple-400 shrink-0 pt-0.5">RELEASE</span>
                    <span className="text-[11px] leading-snug">Production release verified (Health: 100%)</span>
                  </div>
                </div>
              </div>

              {/* Right Column: Readable Workflow YAML File */}
              <div className="lg:col-span-8 bg-[#161718] rounded-xl border border-[#2a2b2e] p-4 font-mono text-[11px] leading-relaxed overflow-x-auto">
                {/* File Header */}
                <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#2a2b2e] text-xs font-sans text-[#a1a1aa]">
                  <div className="flex items-center gap-2">
                    <FileCode size={13} className="text-purple-400" />
                    <span className="font-mono text-[11px] text-[#f3f4f6]">.github/workflows/codebrain-ci.yml</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-emerald-400 font-mono">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span>CI/CD Workflow Active</span>
                  </div>
                </div>

                {/* Workflow YAML Content */}
                <div className="space-y-0.5 select-text text-[#f3f4f6]">
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">01</span>
                    <span className="text-purple-400">name</span>: <span className="text-emerald-300">CodeBrain CI/CD Pipeline</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">02</span>
                    <span className="text-purple-400">on</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">03</span>
                    <span className="pl-4 text-purple-400">push</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">04</span>
                    <span className="pl-8 text-[#a1a1aa]">branches: [ main ]</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">05</span>
                    <span className="pl-4 text-purple-400">pull_request</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">06</span>
                    <span className="pl-8 text-[#a1a1aa]">branches: [ main ]</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">07</span>
                    <span className="text-purple-400">jobs</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">08</span>
                    <span className="pl-4 text-amber-300">test</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">09</span>
                    <span className="pl-8 text-purple-400">runs-on</span>: <span className="text-emerald-300">ubuntu-latest</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">10</span>
                    <span className="pl-8 text-purple-400">steps</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">11</span>
                    <span className="pl-10 text-[#a1a1aa]">- uses: actions/checkout@v4</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">12</span>
                    <span className="pl-10 text-[#a1a1aa]">- name: Set up Python 3.11</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">13</span>
                    <span className="pl-12 text-[#a1a1aa]">uses: actions/setup-python@v5</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">14</span>
                    <span className="pl-10 text-[#a1a1aa]">- name: Run Pytest Test Suite</span>
                  </div>
                  <div className="flex bg-emerald-950/20 text-emerald-300">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-emerald-500">15</span>
                    <span className="pl-12">run: pytest backend/tests/ -q  <span className="text-emerald-400 font-bold ml-2"># Tests Passed</span></span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">16</span>
                    <span className="pl-4 text-amber-300">build</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">17</span>
                    <span className="pl-8 text-purple-400">needs</span>: <span className="text-emerald-300">test</span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">18</span>
                    <span className="pl-8 text-purple-400">steps</span>:
                  </div>
                  <div className="flex bg-emerald-950/20 text-emerald-300">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-emerald-500">19</span>
                    <span className="pl-10">run: npm run build  <span className="text-emerald-400 font-bold ml-2"># Build Complete (539ms)</span></span>
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">20</span>
                    <span className="pl-4 text-amber-300">deploy</span>:
                  </div>
                  <div className="flex text-[#71717a]">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-[#52525b]">21</span>
                    <span className="pl-8 text-purple-400">needs</span>: <span className="text-emerald-300">[test, build]</span>
                  </div>
                  <div className="flex text-purple-300">
                    <span className="w-7 shrink-0 text-right pr-3 select-none text-purple-400">22</span>
                    <span className="pl-10">run: codebrain release --prod  <span className="text-purple-300 font-bold ml-2"># Deployment Successful</span></span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Progressive Bottom Gradient Overlay Merging Smoothly into Page Background #161718 */}
          <div className="absolute inset-x-0 bottom-0 h-44 bg-gradient-to-t from-[#161718] via-[#161718]/85 to-transparent pointer-events-none" />
        </div>

        {/* ── Supporting Feature Labels Underneath the Visual (Matching Reference A) ── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 pt-6 border-t border-[#2a2b2e]/60">
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-[#f3f4f6] tracking-tight">
              Workflow visibility
            </h3>
            <p className="text-[14px] text-[#a1a1aa] leading-relaxed">
              Inspect live pipeline triggers, pull request status, and execution logs in real time.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-[#f3f4f6] tracking-tight">
              Test and build feedback
            </h3>
            <p className="text-[14px] text-[#a1a1aa] leading-relaxed">
              Automated regression testing with immediate diagnostic feedback on failing suites.
            </p>
          </div>

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-[#f3f4f6] tracking-tight">
              Controlled release flow
            </h3>
            <p className="text-[14px] text-[#a1a1aa] leading-relaxed">
              Enforce mandatory quality gates and human sign-offs before pushing to production.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
};

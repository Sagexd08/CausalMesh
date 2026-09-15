"use client";

import agentMarks from "@/lib/landing/agent-marks.json";
import { useInView } from "./Primitives.jsx";

/**
 * The agents this substrate sits under, as a band of their own marks.
 *
 * Above the chart rather than inside it, and that separation is the honest
 * part: the chart plots four measured arms, and these are the clients the
 * substrate accepts. Plotting the logos as data points would imply a
 * per-agent measurement that does not exist — no hosted agent has been run
 * through CausalMesh yet, which the Agents panel further down already says
 * plainly.
 *
 * So the band makes one claim, and it is one the code supports: whichever of
 * these made the call, it passes the same gate and enters the same chain.
 *
 * Marks enter staggered on scroll and then rest. Greyscale at rest and full
 * colour on hover, so eight vendor palettes do not fight the page's single
 * accent — the restraint that makes the marker swipe land is the same
 * restraint that has to apply here.
 */
export default function AgentBand() {
  const [ref, seen] = useInView(0.3);

  return (
    <div ref={ref} className="border-y border-rule-soft bg-paper-raised/60">
      <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-5 px-6 py-5 sm:gap-x-11">
        <span className="text-[12.5px] leading-tight text-ink-500">
          One substrate,
          <br className="hidden sm:block" /> any of these
        </span>

        {agentMarks.map((agent, index) => (
          <span
            key={agent.name}
            // The stagger is a property of the frame rather than a timer, so
            // a mark that scrolls in late still arrives in sequence.
            style={seen ? { animationDelay: `${index * 55}ms` } : undefined}
            className={`group inline-flex items-center gap-2 ${seen ? "cm-mark-in" : "opacity-0"}`}
          >
            <img
              src={agent.src}
              alt=""
              width={18}
              height={18}
              loading="lazy"
              decoding="async"
              className="h-[18px] w-[18px] object-contain opacity-55 grayscale transition-[opacity,filter] duration-300 group-hover:opacity-100 group-hover:grayscale-0"
            />
            <span className="text-[13px] text-ink-600 transition-colors duration-300 group-hover:text-ink-900">
              {agent.name}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

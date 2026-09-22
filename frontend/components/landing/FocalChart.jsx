import Chart from "./Chart.jsx";
import { Mark, Section } from "./Primitives.jsx";

/**
 * The cost/success trade-off, plotted — moved out of the hero so the hero
 * can lead with the live terminal instead. See Chart.jsx's own docstring
 * for why this plot, not a table, is the right shape for this data: it is
 * the one place on the page where the trade-off the whole project measures
 * is visible as geometry rather than read off a row.
 */
export default function FocalChart() {
  return (
    <Section id="tradeoff" className="py-20 md:py-28">
      <div className="max-w-[46ch]">
        <h2 className="font-display text-[clamp(1.875rem,1.545rem+1.318vw,2.6rem)] leading-[1.08] font-bold tracking-tightest text-ink-900">
          Cheap, or <Mark>effective</Mark> — plotted
        </h2>
        <p className="mt-5 text-[15.5px] leading-relaxed text-ink-600">
          Every coordinate below is a measured value from the pilot
          collection, not an illustration.
        </p>
      </div>

      <div className="mt-12">
        <Chart />
      </div>
    </Section>
  );
}

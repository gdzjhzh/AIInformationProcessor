"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

type GooeyTextProps = {
  texts: string[];
  morphTime?: number;
  cooldownTime?: number;
  className?: string;
  textClassName?: string;
};

export function GooeyText({
  texts,
  morphTime = 1,
  cooldownTime = 0.35,
  className,
  textClassName,
}: GooeyTextProps) {
  const text1Ref = React.useRef<HTMLSpanElement>(null);
  const text2Ref = React.useRef<HTMLSpanElement>(null);
  const reactId = React.useId();
  const filterId = React.useMemo(() => `gooey-threshold-${reactId.replace(/:/g, "")}`, [reactId]);

  React.useEffect(() => {
    if (!texts.length) {
      return;
    }

    let textIndex = texts.length - 1;
    let frameId = 0;
    let lastTime = performance.now();
    let morph = 0;
    let cooldown = cooldownTime;

    const setTextPair = () => {
      if (!text1Ref.current || !text2Ref.current) {
        return;
      }

      text1Ref.current.textContent = texts[textIndex % texts.length];
      text2Ref.current.textContent = texts[(textIndex + 1) % texts.length];
    };

    const setMorph = (fraction: number) => {
      if (!text1Ref.current || !text2Ref.current) {
        return;
      }

      const safeFraction = Math.max(fraction, 0.001);
      text2Ref.current.style.filter = `blur(${Math.min(8 / safeFraction - 8, 100)}px)`;
      text2Ref.current.style.opacity = `${Math.pow(fraction, 0.4)}`;

      const inverse = Math.max(1 - fraction, 0.001);
      text1Ref.current.style.filter = `blur(${Math.min(8 / inverse - 8, 100)}px)`;
      text1Ref.current.style.opacity = `${Math.pow(1 - fraction, 0.4)}`;
    };

    const doCooldown = () => {
      morph = 0;
      if (!text1Ref.current || !text2Ref.current) {
        return;
      }

      text2Ref.current.style.filter = "";
      text2Ref.current.style.opacity = "1";
      text1Ref.current.style.filter = "";
      text1Ref.current.style.opacity = "0";
    };

    const doMorph = () => {
      morph -= cooldown;
      cooldown = 0;

      let fraction = morph / morphTime;
      if (fraction > 1) {
        cooldown = cooldownTime;
        fraction = 1;
      }

      setMorph(fraction);
    };

    const animate = (now: number) => {
      frameId = requestAnimationFrame(animate);

      const shouldIncrementIndex = cooldown > 0;
      const delta = (now - lastTime) / 1000;
      lastTime = now;
      cooldown -= delta;

      if (cooldown <= 0) {
        if (shouldIncrementIndex) {
          textIndex = (textIndex + 1) % texts.length;
          setTextPair();
        }
        doMorph();
      } else {
        doCooldown();
      }
    };

    setTextPair();
    frameId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frameId);
    };
  }, [texts, morphTime, cooldownTime]);

  if (!texts.length) {
    return null;
  }

  return (
    <span className={cn("relative block", className)} aria-hidden="true">
      <svg className="absolute h-0 w-0" aria-hidden="true" focusable="false">
        <defs>
          <filter id={filterId}>
            <feColorMatrix
              in="SourceGraphic"
              type="matrix"
              values="1 0 0 0 0
                      0 1 0 0 0
                      0 0 1 0 0
                      0 0 0 255 -140"
            />
          </filter>
        </defs>
      </svg>

      <span className="block h-full w-full" style={{ filter: `url(#${filterId})` }}>
        <span
          ref={text1Ref}
          className={cn("absolute inset-x-0 top-0 inline-block select-none", textClassName)}
          style={{ opacity: 0 }}
        >
          {texts[texts.length - 1]}
        </span>
        <span
          ref={text2Ref}
          className={cn("absolute inset-x-0 top-0 inline-block select-none", textClassName)}
          style={{ opacity: 1 }}
        >
          {texts[0]}
        </span>
      </span>
    </span>
  );
}

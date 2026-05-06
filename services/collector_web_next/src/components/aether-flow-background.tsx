"use client";

import { useEffect, useRef } from "react";

type Particle = {
  x: number;
  y: number;
  directionX: number;
  directionY: number;
  size: number;
  color: string;
};

const MOUSE_RADIUS = 200;

export function AetherFlowBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");

    if (!canvas || !ctx) {
      return;
    }

    let animationFrameId = 0;
    let particles: Particle[] = [];
    let width = window.innerWidth;
    let height = window.innerHeight;
    const mouse: { x: number | null; y: number | null } = { x: null, y: null };

    const drawParticle = (particle: Particle) => {
      ctx.beginPath();
      ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2, false);
      ctx.fillStyle = particle.color;
      ctx.fill();
    };

    const updateParticle = (particle: Particle) => {
      if (particle.x > width || particle.x < 0) {
        particle.directionX = -particle.directionX;
      }
      if (particle.y > height || particle.y < 0) {
        particle.directionY = -particle.directionY;
      }

      if (mouse.x !== null && mouse.y !== null) {
        const dx = mouse.x - particle.x;
        const dy = mouse.y - particle.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance > 0 && distance < MOUSE_RADIUS + particle.size) {
          const forceDirectionX = dx / distance;
          const forceDirectionY = dy / distance;
          const force = (MOUSE_RADIUS - distance) / MOUSE_RADIUS;
          particle.x -= forceDirectionX * force * 5;
          particle.y -= forceDirectionY * force * 5;
        }
      }

      particle.x += particle.directionX;
      particle.y += particle.directionY;
      drawParticle(particle);
    };

    const init = () => {
      particles = [];
      const numberOfParticles = Math.floor((height * width) / 9000);

      for (let i = 0; i < numberOfParticles; i += 1) {
        const size = Math.random() * 2 + 1;
        const x = Math.random() * (width - size * 4) + size * 2;
        const y = Math.random() * (height - size * 4) + size * 2;
        const directionX = Math.random() * 0.4 - 0.2;
        const directionY = Math.random() * 0.4 - 0.2;
        const color = "rgba(191, 128, 255, 0.8)";

        particles.push({ x, y, directionX, directionY, size, color });
      }
    };

    const resizeCanvas = () => {
      const devicePixelRatio = window.devicePixelRatio || 1;
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * devicePixelRatio);
      canvas.height = Math.floor(height * devicePixelRatio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      init();
    };

    const connect = () => {
      for (let a = 0; a < particles.length; a += 1) {
        for (let b = a; b < particles.length; b += 1) {
          const distance =
            (particles[a].x - particles[b].x) * (particles[a].x - particles[b].x) +
            (particles[a].y - particles[b].y) * (particles[a].y - particles[b].y);

          if (distance < (width / 7) * (height / 7)) {
            const opacityValue = Math.max(0.08, 1 - distance / 20000);
            const dxMouse = mouse.x === null ? Number.POSITIVE_INFINITY : particles[a].x - mouse.x;
            const dyMouse = mouse.y === null ? Number.POSITIVE_INFINITY : particles[a].y - mouse.y;
            const distanceMouse = Math.sqrt(dxMouse * dxMouse + dyMouse * dyMouse);

            ctx.strokeStyle =
              mouse.x !== null && distanceMouse < MOUSE_RADIUS
                ? `rgba(255, 255, 255, ${opacityValue})`
                : `rgba(200, 150, 255, ${opacityValue})`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(particles[a].x, particles[a].y);
            ctx.lineTo(particles[b].x, particles[b].y);
            ctx.stroke();
          }
        }
      }
    };

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate);
      ctx.fillStyle = "black";
      ctx.fillRect(0, 0, width, height);

      for (let i = 0; i < particles.length; i += 1) {
        updateParticle(particles[i]);
      }

      connect();
    };

    const handleMouseMove = (event: MouseEvent) => {
      mouse.x = event.clientX;
      mouse.y = event.clientY;
    };

    const handleMouseOut = () => {
      mouse.x = null;
      mouse.y = null;
    };

    window.addEventListener("resize", resizeCanvas);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseout", handleMouseOut);

    resizeCanvas();
    animate();

    return () => {
      window.removeEventListener("resize", resizeCanvas);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseout", handleMouseOut);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 h-screen w-screen"
    />
  );
}

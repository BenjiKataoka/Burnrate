import {
  DitheringShapes, DitheringTypes, ShaderFitOptions, ShaderMount, ditheringFragmentShader,
  getShaderColorFromString as col,
} from "@paper-design/shaders";

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function mountOrb(el: HTMLElement, opts: { size: number; px: number; back: string }) {
  const mount = new ShaderMount(el, ditheringFragmentShader, {
    u_colorBack: col(opts.back), u_colorFront: col("#2e2c29"),
    u_shape: DitheringShapes.sphere, u_type: DitheringTypes["4x4"], u_pxSize: opts.px,
    u_fit: ShaderFitOptions.contain, u_scale: opts.size, u_rotation: 0,
    u_originX: 0.5, u_originY: 0.5, u_offsetX: 0, u_offsetY: 0, u_worldWidth: 0, u_worldHeight: 0,
  }, undefined, 0);
  return {
    set(style: { color: string; speed: number }): void {
      mount.setUniforms({ u_colorFront: col(style.color) });
      mount.setSpeed(reduced ? 0 : style.speed);
    },
  };
}

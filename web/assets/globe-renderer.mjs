import { CAMERA, ATLAS, east, north, front } from './globe-math.mjs';

// A ray-intersected 3D sphere: every fragment samples geographic longitude /
// latitude at its actual sphere intersection. This is not a circular map mask.
const vertexSource = `
attribute vec2 position;
varying vec2 uv;
void main() { uv = position; gl_Position = vec4(position, 0.0, 1.0); }
`;
const fragmentSource = `
precision highp float;
varying vec2 uv;
uniform sampler2D atlas;
uniform mat3 basis;
uniform float distanceToCentre;
uniform float radius;
uniform vec4 bounds;
void main() {
  float d = distanceToCentre;
  vec2 screen = uv / (radius * 2.0);
  vec3 ray = normalize(vec3(screen, -sqrt(d * d - 1.0)));
  float b = d * ray.z;
  float discriminant = b * b - (d * d - 1.0);
  if (discriminant < 0.0) discard;
  vec3 normal = vec3(0.0, 0.0, d) + ray * (-b - sqrt(discriminant));
  vec3 world = basis * normal;
  float longitude = degrees(atan(world.x, world.z));
  float latitude = degrees(asin(clamp(world.y, -1.0, 1.0)));
  vec2 coord = vec2((longitude - bounds.x) / (bounds.y - bounds.x),
    (bounds.w - latitude) / (bounds.w - bounds.z));
  vec3 colour = texture2D(atlas, coord).rgb;
  float facing = max(0.0, dot(normal, -ray));
  float light = dot(normal, normalize(vec3(-0.5, 0.7, 1.0)));
  float shade = 0.86 + 0.16 * light - 0.22 * pow(1.0 - facing, 1.6);
  // Fine paper variation, subordinate to coastlines and daylight.
  float grain = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
  colour = colour * shade + (grain - 0.5) * 0.012;
  gl_FragColor = vec4(colour, smoothstep(0.0, 0.025, facing));
}
`;

export function createGlobeRenderer(canvas, atlas) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true,
    premultipliedAlpha: false, powerPreference: 'low-power', preserveDrawingBuffer: true });
  if (!gl) return null;
  const shaders = [], buffers = [], textures = [];
  const program = gl.createProgram();
  const dispose = () => {
    shaders.forEach(shader => gl.deleteShader(shader));
    buffers.forEach(buffer => gl.deleteBuffer(buffer));
    textures.forEach(texture => gl.deleteTexture(texture));
    gl.deleteProgram(program);
  };
  try {
    if (Math.max(atlas.width, atlas.height) > gl.getParameter(gl.MAX_TEXTURE_SIZE)) throw new Error('Globe texture unavailable');
    for (const [type, source] of [[gl.VERTEX_SHADER, vertexSource], [gl.FRAGMENT_SHADER, fragmentSource]]) {
      const shader = gl.createShader(type);
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('Globe shader unavailable');
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Globe renderer unavailable');
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    buffers.push(buffer);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const texture = gl.createTexture();
    textures.push(texture);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, atlas);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform1i(gl.getUniformLocation(program, 'atlas'), 0);
    gl.uniformMatrix3fv(gl.getUniformLocation(program, 'basis'), false, new Float32Array([...east, ...north, ...front]));
    gl.uniform1f(gl.getUniformLocation(program, 'distanceToCentre'), CAMERA.distance);
    gl.uniform1f(gl.getUniformLocation(program, 'radius'), CAMERA.radius);
    gl.uniform4f(gl.getUniformLocation(program, 'bounds'), ATLAS.west, ATLAS.east, ATLAS.south, ATLAS.north);
    return {
      draw(size, ratio) {
        canvas.width = canvas.height = Math.round(size * ratio);
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      },
      dispose,
    };
  } catch {
    dispose();
    return null; // The locally rendered sphere remains visible.
  }
}

/* Public, self-contained glTF inspection. The scene's IFC-local coordinates are metres, Z up. */
'use strict';
const byId = id => document.getElementById(id);
const layers = {
  'Columns': [.17, .36, .40],
  'Other framing': [.24, .40, .54],
  'Bracing': [.70, .35, .17],
  'Secondary steel': [.22, .51, .49],
  'Panels': [.65, .73, .72]
};
const canvas = byId('model');
const note = byId('loading');
const fmt = value => Number(value).toLocaleString('en-IN', {
  maximumFractionDigits: 3
});
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const extent = () => [
  [Infinity, Infinity, Infinity],
  [-Infinity, -Infinity, -Infinity]
];

function grow(box, p) {
  for (let i = 0; i < 3; i++) {
    box[0][i] = Math.min(box[0][i], p[i]);
    box[1][i] = Math.max(box[1][i], p[i]);
  }
}

function transform(m, x, y, z) {
  return [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[
    6] * y + m[10] * z + m[14]
  ];
}

function readScene(bytes) {
  const dv = new DataView(bytes),
    header = dv.getUint32(12, true);
  if (dv.getUint32(0, true) !== 0x46546c67 || dv.getUint32(4, true) !== 2 || dv.getUint32(8, true) !==
    bytes.byteLength || dv.getUint32(16, true) !== 0x4e4f534a || dv.getUint32(24 + header, true) !==
    0x004e4942) throw Error('Invalid glTF model');
  const doc = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 20, header))),
    start = 28 + header;
  if (doc.extras.case !== document.body.dataset.case || doc.extras.unit !== document.body.dataset.unit)
    throw Error('Model identity differs from this page');

  function data(i) {
    const a = doc.accessors[i],
      v = doc.bufferViews[a.bufferView],
      offset = start + (v.byteOffset || 0) + (a.byteOffset || 0);
    if (a.componentType === 5126) return new Float32Array(bytes, offset, 3 * a.count);
    if (a.componentType === 5123) return new Uint16Array(bytes, offset, a.count);
    if (a.componentType === 5125) return new Uint32Array(bytes, offset, a.count);
    throw Error('Unsupported mesh component');
  }
  const meshes = doc.meshes.map(mesh => {
    const p = mesh.primitives[0],
      i = p.attributes.POSITION,
      a = doc.accessors[i];
    return {
      points: data(i),
      indices: data(p.indices),
      min: a.min,
      max: a.max
    };
  });
  const bounds = extent();
  const objects = doc.nodes[0].children.map((i) => {
    const obj = doc.nodes[i],
      m = meshes[obj.mesh];
    const box = extent();
    for (const x of [m.min[0], m.max[0]])
      for (const y of [m.min[1], m.max[1]])
        for (const z of [m.min[2], m.max[2]]) grow(box, transform(obj.matrix, x, y, z));
    grow(bounds, box[0]);
    grow(bounds, box[1]);
    return {
      ...obj,
      id: i,
      box
    };
  });
  return {
    meshes,
    objects,
    bounds,
    meta: doc.extras
  };
}

function gpuRenderer(gl, scene) {
  const vert =
    `#version 300 es
  layout(location=0) in vec3 pos;layout(location=1) in mat4 instance;layout(location=5) in vec3 colour;layout(location=6) in float objectId;
  uniform mat4 view;out vec3 xyz;out vec3 shade;flat out int ident;
  void main(){vec4 p=instance*vec4(pos,1);xyz=p.xyz;shade=colour;ident=int(objectId+0.5);gl_Position=view*p;}`;
  const frag = `#version 300 es
  precision highp float;precision highp int;in vec3 xyz;in vec3 shade;flat in int ident;uniform bool picking;uniform int selected;out vec4 colour;
  void main(){if(picking){colour=vec4(float(ident&255),float((ident>>8)&255),float((ident>>16)&255),255.)/255.;return;}
  vec3 n=normalize(cross(dFdx(xyz),dFdy(xyz)));float light=.62+.38*abs(dot(n,normalize(vec3(.38,-.47,.80))));
  colour=vec4((ident==selected?vec3(.99,.55,.09):shade)*light,1.);}`;

  function shader(type, source) {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
    return s;
  }
  const program = gl.createProgram();
  gl.attachShader(program, shader(gl.VERTEX_SHADER, vert));
  gl.attachShader(program, shader(gl.FRAGMENT_SHADER, frag));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
  const viewLoc = gl.getUniformLocation(program, 'view'),
    pickLoc = gl.getUniformLocation(program, 'picking'),
    selectLoc = gl.getUniformLocation(program, 'selected');

  function upload(target, array, usage) {
    const b = gl.createBuffer();
    gl.bindBuffer(target, b);
    gl.bufferData(target, array, usage);
    return b;
  }
  const batches = scene.meshes.map(m => {
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    upload(gl.ARRAY_BUFFER, m.points, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    upload(gl.ELEMENT_ARRAY_BUFFER, m.indices, gl.STATIC_DRAW);
    const instances = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, instances);
    for (let c = 0; c < 4; c++) {
      gl.enableVertexAttribArray(c + 1);
      gl.vertexAttribPointer(c + 1, 4, gl.FLOAT, false, 80, c * 16);
      gl.vertexAttribDivisor(c + 1, 1);
    }
    gl.enableVertexAttribArray(5);
    gl.vertexAttribPointer(5, 3, gl.FLOAT, false, 80, 64);
    gl.vertexAttribDivisor(5, 1);
    gl.enableVertexAttribArray(6);
    gl.vertexAttribPointer(6, 1, gl.FLOAT, false, 80, 76);
    gl.vertexAttribDivisor(6, 1);
    return {
      vao,
      instances,
      n: 0,
      count: m.indices.length,
      type: m.indices.BYTES_PER_ELEMENT === 2 ? gl.UNSIGNED_SHORT : gl.UNSIGNED_INT
    };
  });
  gl.bindVertexArray(null);
  gl.useProgram(program);
  gl.enable(gl.DEPTH_TEST);
  gl.disable(gl.DITHER);
  let target = null,
    pickColour = null,
    pickDepth = null,
    oldW = 0,
    oldH = 0;

  function framebuffer() {
    if (oldW === canvas.width && oldH === canvas.height) return;
    if (target) {
      gl.deleteFramebuffer(target);
      gl.deleteTexture(pickColour);
      gl.deleteRenderbuffer(pickDepth);
    }
    oldW = canvas.width;
    oldH = canvas.height;
    target = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, target);
    pickColour = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, pickColour);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, oldW, oldH, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, pickColour, 0);
    pickDepth = gl.createRenderbuffer();
    gl.bindRenderbuffer(gl.RENDERBUFFER, pickDepth);
    gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, oldW, oldH);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, pickDepth);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw Error(
      'Unable to select geometry');
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  function draw(view, selected, picking) {
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.useProgram(program);
    gl.uniformMatrix4fv(viewLoc, false, view);
    gl.uniform1i(selectLoc, selected);
    gl.uniform1i(pickLoc, picking ? 1 : 0);
    if (picking) gl.clearColor(0, 0, 0, 0);
    else gl.clearColor(.916, .941, .927, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    for (const b of batches) {
      if (b.n) {
        gl.bindVertexArray(b.vao);
        gl.drawElementsInstanced(gl.TRIANGLES, b.count, b.type, 0, b.n);
      }
    }
    gl.bindVertexArray(null);
  }
  return {
    mode: 'Solid view',
    filter(rows) {
      const per = batches.map(() => []);
      for (const o of rows) per[o.mesh].push(o);
      batches.forEach((b, i) => {
        const rows = per[i];
        b.n = rows.length;
        if (!b.n) return;
        const block = new Float32Array(b.n * 20);
        rows.forEach((o, j) => {
          block.set(o.matrix, j * 20);
          block.set(layers[o.extras.layer], j * 20 + 16);
          block[j * 20 + 19] = o.id;
        });
        gl.bindBuffer(gl.ARRAY_BUFFER, b.instances);
        gl.bufferData(gl.ARRAY_BUFFER, block, gl.DYNAMIC_DRAW);
      });
    },
    draw(view, sel) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      draw(view, sel, false);
    },
    pick(x, y, view, sel) {
      framebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, target);
      draw(view, sel, true);
      const pixel = new Uint8Array(4);
      gl.readPixels(x, canvas.height - 1 - y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      return pixel[0] + 256 * pixel[1] + 65536 * pixel[2];
    }
  };
}

// A 2D canvas can still navigate and pick the three-dimensional member axes on machines without WebGL.
function lineRenderer(canvas2d, scene) {
  const ctx = canvas2d.getContext('2d');
  let rows = [],
    lines = [];
  return {
    mode: 'Line view (WebGL unavailable)',
    filter(r) {
      rows = r;
    },
    draw(view, sel) {
      ctx.fillStyle = '#eaf0ed';
      ctx.fillRect(0, 0, canvas2d.width, canvas2d.height);
      lines = [];

      function project(m, p) {
        const w = transform(m, ...p),
          q = transform(view, ...w);
        return [(q[0] + 1) * canvas2d.width / 2, (1 - q[1]) * canvas2d.height / 2];
      }
      for (const row of rows) {
        const mesh = scene.meshes[row.mesh],
          e = row.extras,
          m = row.matrix,
          color = layers[e.layer].map(v => Math.round(v * 255));
        ctx.strokeStyle = row.id === sel ? '#e17618' : `rgb(${color.join(',')})`;
        ctx.lineWidth = row.id === sel ? 3 : 1;
        ctx.beginPath();
        if (e.layer === 'Panels') {
          const a = mesh.points,
            idx = mesh.indices;
          for (let i = 0; i < idx.length; i += 3) {
            const tri = [idx[i], idx[i + 1], idx[i + 2]].map(k => project(m, [a[3 * k], a[3 * k + 1], a[
              3 * k + 2]]));
            ctx.moveTo(...tri[0]);
            ctx.lineTo(...tri[1]);
            ctx.lineTo(...tri[2]);
            ctx.closePath();
          }
        } else {
          const a = project(m, [0, 0, mesh.min[2]]),
            b = project(m, [0, 0, mesh.max[2]]);
          ctx.moveTo(...a);
          ctx.lineTo(...b);
          lines.push([row.id, a, b]);
        }
        ctx.stroke();
      }
    },
    pick(x, y) {
      let best = 8,
        id = 0;
      for (const [n, a, b] of lines) {
        const dx = b[0] - a[0],
          dy = b[1] - a[1],
          t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)));
        const d = Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy);
        if (d < best) {
          best = d;
          id = n;
        }
      }
      return id;
    }
  };
}

function inspect(scene) {
  const gl = canvas.getContext('webgl2', {
    antialias: true,
    alpha: false
  });
  const renderer = gl ? gpuRenderer(gl, scene) : lineRenderer(canvas, scene);
  const {
    objects,
    meta,
    bounds
  } = scene, index = new Map(objects.map(o => [o.id, o]));
  let yaw, pitch, scale, center, view, visible = [],
    selected = 0,
    pending = false;
  const boxSize = bounds[1].map((x, i) => x - bounds[0][i]),
    radius = Math.max(1, Math.hypot(...boxSize) / 2);
  const level = byId('level'),
    layer = byId('layer'),
    panels = byId('panels'),
    search = byId('search'),
    list = byId('objects');
  for (const [control, values] of [
      [level, objects.map(o => o.extras.level)],
      [layer, objects.map(o => o.extras.layer)]
    ]) {
    for (const value of [...new Set(values)].filter(Boolean).sort((a, b) => a.localeCompare(b,
      undefined, {
        numeric: true
      }))) control.add(new Option(value, value));
  }

  function camera() {
    const cy = Math.cos(yaw),
      sy = Math.sin(yaw),
      cp = Math.cos(pitch),
      sp = Math.sin(pitch);
    const right = [-sy, cy, 0],
      up = [-cy * sp, -sy * sp, cp],
      towards = [cy * cp, sy * cp, sp];
    const x = right.map(v => v * scale / Math.max(1, canvas.width / canvas.height)),
      y = up.map(v => v * scale / Math.max(1, canvas.height / canvas.width)),
      z = towards.map(v => -v / (radius * 4));
    view = new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x,
      center), -dot(y, center), -dot(z, center), 1]);
    return [right, up];
  }

  function draw() {
    pending = false;
    const ratio = Math.min(window.devicePixelRatio || 1, 2),
      w = Math.max(1, Math.round(canvas.clientWidth * ratio)),
      h = Math.max(1, Math.round(canvas.clientHeight * ratio));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    camera();
    renderer.draw(view, selected);
  }

  function redraw() {
    if (!pending) {
      pending = true;
      requestAnimationFrame(draw);
    }
  }

  function fit() {
    center = bounds[0].map((v, i) => (v + bounds[1][i]) / 2);
    const cy = Math.cos(yaw),
      sy = Math.sin(yaw),
      cp = Math.cos(pitch),
      sp = Math.sin(pitch);
    const right = [-sy, cy, 0],
      up = [-cy * sp, -sy * sp, cp],
      aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
    const halfExtent = axis => boxSize.reduce((sum, side, i) => sum + side * Math.abs(axis[i]) / 2, 0);
    scale = .91 * Math.min(Math.max(1, aspect) / Math.max(.01, halfExtent(right)), Math.max(1, 1 /
      aspect) / Math.max(.01, halfExtent(up)));
    redraw();
  }

  function preset() {
    const chosen = byId('camera').value;
    [yaw, pitch] = ({
      Isometric: [-.92, .44],
      Plan: [-Math.PI / 2, Math.PI / 2],
      Front: [-Math.PI / 2, 0],
      Side: [0, 0]
    })[chosen];
    fit();
  }

  function entry(dl, label, value) {
    if (value === null || value === undefined || value === '') return;
    const dt = document.createElement('dt'),
      dd = document.createElement('dd');
    dt.textContent = label;
    dd.textContent = value;
    dl.append(dt, dd);
  }

  function select(id) {
    selected = id || 0;
    const o = index.get(selected),
      detail = byId('properties');
    detail.replaceChildren();
    const title = document.createElement('h3');
    title.textContent = o ? o.name : 'Object details';
    detail.append(title);
    if (o) {
      const d = o.extras,
        dl = document.createElement('dl');
      entry(dl, 'Role', d.role);
      entry(dl, 'Section', d.end_profile ? `${d.profile} → ${d.end_profile}` : d.profile);
      entry(dl, 'Material', d.material);
      entry(dl, 'Level', d.level);
      entry(dl, 'Workline length', d.length_mm === undefined ? null : fmt(d.length_mm) + ' mm');
      entry(dl, 'Panel thickness', d.thickness_mm === undefined ? null : fmt(d.thickness_mm) + ' mm');
      entry(dl, 'Openings in issued solid', d.openings);
      entry(dl, 'End cutbacks', d.end_cutbacks_mm?.map(v => fmt(v) + ' mm').join(' / '));
      entry(dl, 'IFC GlobalId', d.guid);
      for (const k of d.checks) {
        const c = meta.checks[k];
        if (c) entry(dl, 'Linked source check',
          `${c.description} · ${c.status}${typeof c.utilization==='number'?' · D/C '+fmt(c.utilization):''}`
          );
      }
      detail.append(dl);
      if (!Array.from(list.options).some(p => p.value === String(id))) list.add(new Option(
        `${o.name} · ${d.profile||d.role}`, String(id)));
      list.value = String(id);
    } else {
      const p = document.createElement('p');
      p.textContent = 'Select steel or a panel to see its issued properties.';
      detail.append(p);
      list.value = '';
    }
    redraw();
  }

  function filter() {
    const query = search.value.trim().toLowerCase();
    visible = objects.filter(o => (!level.value || o.extras.level === level.value) && (!layer.value || o
      .extras.layer === layer.value) && (panels.checked || o.extras.layer !== 'Panels'));
    const matches = visible.filter(o => !query || [o.name, o.extras.profile, o.extras.end_profile, o
      .extras.role, o.extras.guid
    ].some(x => (x || '').toLowerCase().includes(query)));
    list.replaceChildren(new Option('Select an object', ''));
    for (const o of matches.slice(0, 150)) list.add(new Option(
      `${o.name} · ${o.extras.profile||o.extras.role}`, String(o.id)));
    byId('matches').textContent = matches.length > 150 ?
      `Showing 150 of ${fmt(matches.length)} matches. Refine the search to see more.` :
      `${fmt(matches.length)} matching objects`;
    renderer.filter(visible);
    select(visible.some(o => o.id === selected) ? selected : 0);
  }

  function zoom(factor) {
    scale = Math.max(.025 / radius, Math.min(500 / radius, scale * factor));
    redraw();
  }

  function pan(dx, dy) {
    const [right, up] = camera(), factor = 2 / (scale * Math.min(canvas.clientWidth, canvas
    .clientHeight));
    center = center.map((v, i) => v - dx * right[i] * factor + dy * up[i] * factor);
  }
  byId('summary').textContent =
    `${fmt(meta.members)} members · ${fmt(meta.panels)} panels · ${renderer.mode}`;
  for (const c of [level, panels]) c.addEventListener('change', filter);
  layer.addEventListener('change', () => {
    if (layer.value === 'Panels') panels.checked = true;
    filter();
  });
  search.addEventListener('input', filter);
  list.addEventListener('change', () => select(Number(list.value)));
  byId('fit').onclick = fit;
  byId('camera').onchange = preset;
  const pointers = new Map();
  let moved = 0,
    hadPinch = false;
  canvas.oncontextmenu = e => e.preventDefault();
  canvas.addEventListener('pointerdown', e => {
    canvas.focus({
      preventScroll: true
    });
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 1) {
      moved = 0;
      hadPinch = false;
    } else hadPinch = true;
  });
  canvas.addEventListener('pointermove', e => {
    const old = pointers.get(e.pointerId);
    if (!old) return;
    const x = e.clientX,
      y = e.clientY,
      dx = x - old[0],
      dy = y - old[1];
    moved += Math.hypot(dx, dy);
    if (pointers.size === 2) {
      const other = Array.from(pointers).find(([k]) => k !== e.pointerId)[1];
      const before = Math.hypot(old[0] - other[0], old[1] - other[1]);
      if (before > 1) zoom(Math.hypot(x - other[0], y - other[1]) / before);
      pan(dx / 2, dy / 2);
    } else if (e.shiftKey || e.buttons === 2) pan(dx, dy);
    else {
      yaw -= dx * .009;
      pitch = Math.max(-1.56, Math.min(1.56, pitch + dy * .009));
    }
    pointers.set(e.pointerId, [x, y]);
    redraw();
  });
  canvas.addEventListener('pointerup', e => {
    if (!hadPinch && moved < 5 && e.button === 0) {
      draw();
      const r = canvas.getBoundingClientRect();
      select(renderer.pick(Math.floor((e.clientX - r.left) * canvas.width / r.width), Math.floor((e
        .clientY - r.top) * canvas.height / r.height), view, selected));
    }
    pointers.delete(e.pointerId);
  });
  canvas.addEventListener('pointercancel', e => pointers.delete(e.pointerId));
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    zoom(Math.exp(-Math.sign(e.deltaY) * .15));
  }, {
    passive: false
  });
  canvas.addEventListener('keydown', e => {
    switch (e.key) {
      case 'ArrowLeft':
        yaw -= .09;
        break;
      case 'ArrowRight':
        yaw += .09;
        break;
      case 'ArrowUp':
        pitch = Math.min(1.57, pitch + .09);
        break;
      case 'ArrowDown':
        pitch = Math.max(-1.57, pitch - .09);
        break;
      case '+':
      case '=':
        zoom(1.2);
        break;
      case '-':
        zoom(.83);
        break;
      default:
        return;
    }
    e.preventDefault();
    redraw();
  });
  new ResizeObserver(redraw).observe(canvas);
  preset();
  filter();
  draw();
  canvas.dataset.ready = 'true';
  canvas.dataset.mode = gl ? 'solid' : 'line';
  note.textContent = '';
}
(async () => {
  try {
    const response = await fetch(document.body.dataset.scene);
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    inspect(readScene(await response.arrayBuffer()));
  } catch (e) {
    note.textContent = `Unable to open this view (${e.message}).`;
    console.error(e);
  }
})();

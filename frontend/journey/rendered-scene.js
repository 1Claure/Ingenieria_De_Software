import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// One fixed GLB world. Scroll moves a perspective camera continuously through
// the exported reading stops; no still-image planes or frame sequences exist.
export function createRenderedJourney({canvas, worldManifestUrl, onReady, onError}) {
  let disposed = false, failed = false, ready = false, worldReady = false;
  let width = 1, height = 1, progress = 0, targetProgress = 0;
  let raf = 0, previousTime = 0, visible = true, dirty = true;
  let asset = null, environmentTarget = null, sun = null, sky = null;
  let stops = [], positionCurve = null, targetCurve = null;
  const controller = new AbortController();
  const cleanups = [];
  const cameraTarget = new THREE.Vector3();
  const scene = new THREE.Scene();
  const horizonColor = new THREE.Color('#c4c6bf');
  scene.background = horizonColor.clone();
  const camera = new THREE.PerspectiveCamera(28, 1, .03, 3000);
  camera.filmGauge = 36;
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: false, powerPreference: 'low-power'});
  renderer.debug.onShaderError = () => fail(new Error('No se pudo preparar la visualización 3D'));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = .95;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.shadowMap.autoUpdate = false;

  function fail(error) {
    if (disposed || failed) return;
    failed = true;
    controller.abort();
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    onError?.(error instanceof Error ? error : new Error(String(error)));
  }
  function schedule() {
    if (!disposed && !failed && !raf && visible && !document.hidden) raf = requestAnimationFrame(draw);
  }

  function disposeAsset(gltf) {
    const geometries = new Set(), materials = new Set(), textures = new Set(), images = new Set();
    const roots = gltf.scenes?.length ? gltf.scenes : [gltf.scene];
    for (const root of roots) root?.traverse(object => {
      if (object.geometry) geometries.add(object.geometry);
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        if (!material) continue;
        materials.add(material);
        for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
      }
    });
    textures.forEach(texture => {
      const image = texture.source?.data || texture.image;
      if (image && typeof image.close === 'function') images.add(image);
      texture.dispose();
    });
    materials.forEach(material => material.dispose());
    geometries.forEach(geometry => geometry.dispose());
    images.forEach(image => image.close());
  }

  function vector(value, label) {
    if (!Array.isArray(value) || value.length !== 3 || !value.every(Number.isFinite)) {
      throw new Error(`Coordenadas inválidas en ${label}`);
    }
    return new THREE.Vector3(...value);
  }

  function createOutdoorSky(sunDirection) {
    // A world-space dome, not an image backdrop: its horizon remains fixed
    // while the perspective camera travels from the surface into the section.
    const material = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      uniforms: {
        zenithColor: {value: new THREE.Color('#849dad')},
        horizonColor: {value: horizonColor.clone()},
        groundColor: {value: new THREE.Color('#77776b')},
        sunDirection: {value: sunDirection.clone()},
      },
      vertexShader: `
        varying vec3 journeySkyDirection;
        void main() {
          journeySkyDirection = position;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform vec3 zenithColor;
        uniform vec3 horizonColor;
        uniform vec3 groundColor;
        uniform vec3 sunDirection;
        varying vec3 journeySkyDirection;
        void main() {
          vec3 direction = normalize(journeySkyDirection);
          float elevation = direction.y;
          float skyMix = pow(clamp(elevation, 0.0, 1.0), 0.46);
          vec3 color = mix(horizonColor, zenithColor, skyMix);
          color = mix(color, groundColor, 1.0 - smoothstep(-0.48, -0.025, elevation));
          float sunHaze = pow(max(dot(direction, sunDirection), 0.0), 14.0);
          color += vec3(0.055, 0.045, 0.030) * sunHaze * smoothstep(-0.03, 0.12, elevation);
          gl_FragColor = vec4(color, 1.0);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }
      `,
    });
    const dome = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 16), material);
    dome.frustumCulled = false;
    dome.renderOrder = -100;
    return dome;
  }

  function gradeGeology(material) {
    if (material.userData.journeyGeologyGrade) return;
    material.userData.journeyGeologyGrade = true;
    const previousCompile = material.onBeforeCompile;
    material.onBeforeCompile = function(shader, activeRenderer) {
      previousCompile.call(this, shader, activeRenderer);
      // Grade only base colour. Normal, roughness and AO maps still describe
      // the rock surface; the site's gravel keeps its original sandy colour.
      shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
        #include <map_fragment>
        float journeyRockLuminance = dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722));
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(journeyRockLuminance), 0.60);
      `);
    };
    material.customProgramCacheKey = () => 'journey-geology-mineral-v1';
    material.needsUpdate = true;
  }

  function configureWorld(manifest, model) {
    if (!Array.isArray(manifest.cameraStops) || manifest.cameraStops.length < 2) {
      throw new Error('El recorrido no contiene posiciones de cámara');
    }
    stops = manifest.cameraStops.map((stop, index) => ({
      progress: Number.isFinite(stop.progress) ? stop.progress : index/(manifest.cameraStops.length-1),
      position: vector(stop.position, 'cameraStops.position'),
      target: vector(stop.target, 'cameraStops.target'),
      fov: Number.isFinite(stop.fov) ? stop.fov : 28,
      filmOffset: Number.isFinite(stop.filmOffset) ? stop.filmOffset : -8.64,
    })).sort((a, b) => a.progress-b.progress);
    if (stops[0].progress !== 0 || stops.at(-1).progress !== 1 || stops.some((stop, index) =>
      stop.fov < 10 || stop.fov > 90 || stop.position.distanceToSquared(stop.target) < .000001 ||
      (index > 0 && stop.progress <= stops[index-1].progress))) {
      throw new Error('Las posiciones del recorrido no son válidas');
    }
    positionCurve = new THREE.CatmullRomCurve3(stops.map(stop => stop.position), false, 'centripetal');
    targetCurve = new THREE.CatmullRomCurve3(stops.map(stop => stop.target), false, 'centripetal');

    model.updateMatrixWorld(true);
    const worldBounds = new THREE.Box3().setFromObject(model);
    if (worldBounds.isEmpty()) throw new Error('La escena 3D está vacía');
    const operationBounds = manifest.operationBounds
      ? new THREE.Box3(vector(manifest.operationBounds.min, 'operationBounds.min'), vector(manifest.operationBounds.max, 'operationBounds.max'))
      : worldBounds.clone();
    const center = operationBounds.getCenter(new THREE.Vector3());
    const diagonal = Math.max(10, operationBounds.getSize(new THREE.Vector3()).length());
    const worldDiagonal = Math.max(diagonal, worldBounds.getSize(new THREE.Vector3()).length());
    const pathDistance = Math.max(...stops.map(stop => stop.position.distanceTo(center)));
    camera.near = Math.max(.02, diagonal/15000);
    camera.far = Math.max(1000, worldDiagonal*3, pathDistance+worldDiagonal*2);
    camera.updateProjectionMatrix();
    // Haze conceals the far terrain boundary without washing out the nearby
    // machinery or section, both of which stay within the clear range.
    scene.fog = new THREE.Fog(horizonColor, Math.max(diagonal*1.25, pathDistance*.95), Math.max(diagonal*8, pathDistance*4));

    model.traverse(object => {
      if (!object.isMesh) return;
      object.castShadow = true;
      object.receiveShadow = true;
      const isGeology = object.userData.renderRole === 'geology' || object.name.startsWith('geology__');
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        if (!material) continue;
        material.dithering = true;
        if (isGeology) gradeGeology(material);
      }
    });
    scene.add(new THREE.HemisphereLight('#dbe2e5', '#928575', 1.1));
    const sunDirection = new THREE.Vector3(-.7, 1.2, .8).normalize();
    sun = new THREE.DirectionalLight('#fff0d9', 2.15);
    sun.position.copy(center).addScaledVector(sunDirection, diagonal*1.6);
    sun.target.position.copy(center);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    const radius = diagonal*.65;
    Object.assign(sun.shadow.camera, {left: -radius, right: radius, top: radius, bottom: -radius, near: .1, far: diagonal*4});
    sun.shadow.normalBias = diagonal*.00025;
    sun.shadow.bias = -.00008;
    sun.shadow.camera.updateProjectionMatrix();
    scene.add(sun, sun.target);

    sky = createOutdoorSky(sunDirection);
    sky.scale.setScalar(camera.far*.45);
    scene.add(sky);
    const environmentScene = new THREE.Scene();
    const environmentSky = new THREE.Mesh(sky.geometry, sky.material);
    environmentSky.scale.setScalar(50);
    environmentScene.add(environmentSky);
    const pmrem = new THREE.PMREMGenerator(renderer);
    try {
      environmentTarget = pmrem.fromScene(environmentScene, .06, .1, 100);
      scene.environment = environmentTarget.texture;
      scene.environmentIntensity = .65;
    } finally {
      environmentScene.clear();
      pmrem.dispose();
    }
    renderer.shadowMap.needsUpdate = true;
    updateCamera();
  }

  function pathLocation(value) {
    let index = 0;
    while (index < stops.length-2 && value > stops[index+1].progress) index++;
    const local = THREE.MathUtils.clamp((value-stops[index].progress)/(stops[index+1].progress-stops[index].progress), 0, 1);
    return {index, local, curveT: (index+local)/(stops.length-1)};
  }
  function updateCamera() {
    if (!positionCurve || !targetCurve) return;
    const {index, local, curveT} = pathLocation(progress);
    positionCurve.getPoint(curveT, camera.position);
    sky?.position.copy(camera.position);
    targetCurve.getPoint(curveT, cameraTarget);
    camera.lookAt(cameraTarget);
    const fov = THREE.MathUtils.lerp(stops[index].fov, stops[index+1].fov, local);
    const filmOffset = THREE.MathUtils.lerp(stops[index].filmOffset, stops[index+1].filmOffset, local);
    if (camera.fov !== fov || camera.filmOffset !== filmOffset) {
      camera.fov = fov;
      // The Blender export already composes the scene for text on the left.
      // Apply its film shift once; adding a view offset would crop the world.
      camera.filmOffset = filmOffset;
      camera.updateProjectionMatrix();
    }
  }

  async function loadWorld() {
    try {
      if (!worldManifestUrl) throw new Error('Falta la escena del recorrido');
      const manifestUrl = new URL(worldManifestUrl, window.location.href);
      if (manifestUrl.origin !== window.location.origin) throw new Error('La escena debe servirse desde la aplicación');
      const manifestResponse = await fetch(manifestUrl, {signal: controller.signal});
      if (!manifestResponse.ok) throw new Error(`Escena: ${manifestResponse.status}`);
      const manifest = await manifestResponse.json();
      if (disposed || failed || controller.signal.aborted) return;
      if (typeof manifest.model !== 'string') throw new Error('La escena no declara su modelo 3D');
      const modelUrl = new URL(manifest.model, manifestUrl);
      if (modelUrl.origin !== window.location.origin) throw new Error('El modelo debe servirse desde la aplicación');
      if (manifest.version) modelUrl.searchParams.set('v', manifest.version);
      const modelResponse = await fetch(modelUrl, {signal: controller.signal, cache: 'force-cache'});
      if (!modelResponse.ok) throw new Error(`Modelo 3D: ${modelResponse.status}`);
      const buffer = await modelResponse.arrayBuffer();
      if (disposed || failed || controller.signal.aborted) return;
      const loaded = await new GLTFLoader().parseAsync(buffer, new URL('.', modelUrl).href);
      if (disposed || failed || controller.signal.aborted) {disposeAsset(loaded);return;}
      asset = loaded;
      scene.add(asset.scene);
      configureWorld(manifest, asset.scene);
      if (disposed || failed) return;
      worldReady = true;
      dirty = true;
      schedule();
    } catch (error) {
      if (!disposed && !failed && error.name !== 'AbortError') fail(error);
    }
  }

  function draw(time) {
    raf = 0;
    if (disposed || failed || !worldReady || !visible || document.hidden) return;
    const dt = previousTime ? Math.min(.06, (time-previousTime)/1000) : 1/60;
    previousTime = time;
    const previousProgress = progress;
    const moving = Math.abs(targetProgress-progress) > .00015;
    progress = moving ? THREE.MathUtils.lerp(progress, targetProgress, 1-Math.exp(-30*dt)) : targetProgress;
    if (moving || dirty || progress !== previousProgress) {
      try {updateCamera();renderer.render(scene, camera);}
      catch (error) {fail(error);return;}
      if (disposed || failed) return;
      dirty = false;
      if (!ready) {ready = true;onReady?.();}
    }
    if (moving) schedule();
  }
  function resize(nextWidth, nextHeight) {
    if (disposed || failed) return;
    width = Math.max(1, Number(nextWidth) || 1);
    height = Math.max(1, Number(nextHeight) || 1);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    renderer.setSize(width, height, false);
    camera.aspect = width/height;
    camera.updateProjectionMatrix();
    dirty = true;
    schedule();
  }
  function setProgress(value) {
    if (disposed || failed || !Number.isFinite(value)) return;
    targetProgress = THREE.MathUtils.clamp(value, 0, 1);
    if (!ready) progress = targetProgress;
    dirty = true;
    schedule();
  }

  const visibility = () => {
    previousTime = 0;
    if (document.hidden) {if (raf) cancelAnimationFrame(raf);raf = 0;}
    else {dirty = true;schedule();}
  };
  document.addEventListener('visibilitychange', visibility);
  cleanups.push(() => document.removeEventListener('visibilitychange', visibility));
  const observer = new IntersectionObserver(entries => {
    visible = entries.some(entry => entry.isIntersecting);
    previousTime = 0;
    if (!visible) {if (raf) cancelAnimationFrame(raf);raf = 0;}
    else {dirty = true;schedule();}
  }, {rootMargin: '120px'});
  observer.observe(canvas);
  cleanups.push(() => observer.disconnect());
  const contextLost = event => {event.preventDefault();fail(new Error('WebGL no disponible'));};
  canvas.addEventListener('webglcontextlost', contextLost);
  cleanups.push(() => canvas.removeEventListener('webglcontextlost', contextLost));

  resize(canvas.clientWidth || 1000, canvas.clientHeight || 600);
  loadWorld();
  return {setProgress, resize, dispose() {
    if (disposed) return;
    disposed = true;
    controller.abort();
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    cleanups.forEach(cleanup => cleanup());
    if (asset) {disposeAsset(asset);asset = null;}
    sky?.geometry.dispose();
    sky?.material.dispose();
    sky = null;
    environmentTarget?.dispose();
    environmentTarget = null;
    sun?.shadow.map?.dispose();
    scene.environment = null;
    scene.clear();
    renderer.renderLists.dispose();
    renderer.dispose();
  }};
}


//#define DYNAMIC_WATER // requires u_WaterTime update in game_states_play_share.cpp

#define DIFFUSE_LIGHTING
#define SPECULAR_LIGHTING
#define DIRECT_LIGHTING
#define AMBIENT_LIGHTING

// Some undefs for quick debugging
//#undef ALBEDO_DETAIL
//#undef GLOSS_MAP
//#undef WORLD_GLOSS_MAP
//#undef GLOSS_DETAIL
//#undef NORMAL_MAP
//#undef WORLD_NORMAL_MAP
//#undef NIGHT
//#undef PLANAR_REFLECTION
//#undef WORLD_NORMAL_MAP_UNIQUE
//#undef SUN_FOG
//#undef FLAT_COLOUR

//%include utility.xsh
//%include pbr_utility.xsh

#ifdef FLAT_COLOUR
uniform lowp vec3 mu_Colour;
#else
uniform lowp sampler2D s_Texture0;	// Albedo map
#endif

#if defined(VERTEX_WET) || defined(VERTEX_COLOUR) || defined(VERTEX_ALPHA) 
varying lowp vec4 v_VertexColour;
#endif

#ifdef ALBEDO_SCALE
uniform highp float mu_AlbedoScale;
#endif

#if defined(SHADOW_MAP) || defined(CACHED_SHADOW_MAP) || defined(PARTICLE_SHADOW)
uniform highp vec2 u_ViewportSizeInv;
#endif
#if defined(SHADOW_MAP) || defined(CACHED_SHADOW_MAP) 
uniform lowp sampler2D s_Texture1;	// Light map
#endif

#if defined(NORMAL_MAP) || defined(WORLD_NORMAL_MAP) || defined(WORLD_NORMAL_MAP_UNIQUE)
uniform lowp sampler2D s_Texture2;	// Tangent-space normal map
#endif

#ifdef NORMAL_SCALE
uniform highp float mu_NormalScale;
#endif

#if defined(GLOSS_MAP) || defined(WORLD_GLOSS_MAP) || defined(NIGHT_GLOW) || defined(GLOW) || defined(METALLIC_MAP) || defined(SPECULAR_MAP)
uniform lowp sampler2D s_Texture3;	// Gloss map
#endif
#if !(defined(GLOSS_MAP) || defined(WORLD_GLOSS_MAP))
uniform highp float mu_Gloss;		// Gloss value (material spreadsheet)
#endif
#if defined(WORLD_GLOSS_MAP)
varying highp vec2 v_WorldGlossMapCoord;
#endif

#if defined(SPECULAR_MAP)
uniform lowp sampler2D s_Texture6;
#endif

#ifdef DETAIL
//varying highp vec2 v_DetailMapCoord;
#endif
varying highp vec2 v_DetailMapCoord;

#if defined(ALBEDO_DETAIL) || defined(GLOSS_DETAIL)
uniform lowp sampler2D s_Texture5;	// Detail map - modulates albedo, adds gloss
#endif

//#ifdef DETAIL_ROUGH
//uniform lowp sampler2D s_Texture3;	// Detail map - modulates diffuse map
//#endif

#ifdef SCATTERED_TRANSLUCENCY
	uniform mediump float u_TranslucencyScale;
	uniform mediump float mu_TranslucencyOpacity;
	uniform mediump float mu_TranslucencyFalloff;
#endif


uniform highp vec3 mu_Spec;			// Base specular colour (material spreadsheet)

uniform highp sampler2D s_brdfMap;			// Preintegrated BRDF
//uniform mediump sampler2D s_pbrMap;			// Preintegrated env map
#ifndef RENDER_TO_CUBEMAP
uniform lowp samplerCube s_cubeMap;			// Cube map
uniform lowp sampler2D s_waterReflection;
#endif

uniform highp vec4 u_SkyRotation;	// Packed Y-Axis rotation matrix of the sky dome. mat2(u_SkyRotation.xy, u_SkyRotation.zw)

uniform highp vec3 u_LightDirWorldSpace;

uniform highp vec3 u_CamPos;
uniform highp vec3 u_CamX;
uniform highp vec3 u_CamY;
uniform highp vec3 u_CamZ;

varying highp vec3 v_Pos_W;
varying highp vec3 v_Normal_W;

varying highp vec2 v_TexCoord0;
#if defined(SHADOW_MAP) && !defined(CACHED_SHADOW_MAP)
varying highp vec2 v_TexCoord1;
#endif

#if defined(SEPARATE_ALPHA) || defined(ALBEDO_TO_NORMAL)
uniform sampler2D s_Texture4;
varying highp vec2 v_TexCoord2;
#endif

#if defined(NORMAL_MAP)
varying highp vec3 v_Tangent_W;
varying highp vec3 v_Bitangent_W;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		varying lowp vec3 v_FogColour;
		varying lowp float v_FogFactor;
	#else
		uniform lowp vec3 u_FogColour;
		varying lowp float v_FogFactor;
	#endif
#endif

uniform lowp vec3 u_LightAmbientColour;
uniform lowp vec3 u_LightSpecularColour;
uniform highp vec4 u_PbrWetParams;

#ifdef PLANAR_REFLECTION
uniform lowp sampler2D s_PlanarReflectionTexture;
uniform highp vec2 u_PlanarReflectionSizeInv;
#endif

#ifdef PARTICLE_SHADOW
uniform lowp sampler2D u_ParticleShadowTexture;
#endif

#if defined(NIGHT)
	uniform highp vec4 u_HeadLightFalloff;
	uniform highp vec2 u_HeadLightAtten;
	uniform highp vec3 u_HeadLightPos;
	uniform mediump vec3 u_HeadLightColour;
	varying highp vec3 v_PosHeadLightSpace;
#endif

#if defined(DYNAMIC_WATER)

uniform highp float u_WaveTime;

highp vec3 GerstnerWaveValues(highp vec2 position, highp vec2 D, highp float amplitude, highp float wavelength, highp float Q, highp float timer)
{
	highp float w = 2.0 * 3.14159265 / wavelength;
	highp float dotD = dot(position, D);
	highp float v = w * dotD + timer;
	return highp vec3(cos(v), sin(v), w);
}

mediump vec3 GerstnerWaveNormal(highp vec2 D, highp float A, highp float Q, highp vec3 vals)
{
	mediump float C = vals.x;
	mediump float S = vals.y;
	mediump float w = vals.z;
	mediump float WA = w * A;
	mediump float WAC = WA * C;
	mediump vec3 normal = vec3(-D.x * WAC, 1.0 - Q * WA * S, -D.y * WAC);
	return normalize(normal);
}
#endif

void main()
{
	highp vec4 u_PbrLightParams = vec4(1.0, 0.0, 1.0, 1.0); // TO_DO

	///////////////////////////////////////////////// Albedo

#ifdef FLAT_COLOUR
	lowp vec4 diffuseColour = vec4(mu_Colour, 1.0);
#else
	#ifdef ALBEDO_SCALE
		lowp vec4 diffuseColour = texture2DWithBias(s_Texture0, v_TexCoord0 * mu_AlbedoScale);
		#elif defined(ALBEDO_TO_NORMAL)
			lowp vec4 diffuseColour = texture2DWithBias(s_Texture0, v_TexCoord2);
		#else
			lowp vec4 diffuseColour = texture2DWithBias(s_Texture0, v_TexCoord0);
	#endif

	#ifdef ALPHA_TEST // for testing
		if (diffuseColour.a < 0.35)
		{
			discard;
		}
	#endif

	#if defined(ALBEDO_DETAIL) || defined(GLOSS_DETAIL)
		lowp vec4 detailTexture = texture2DWithBias(s_Texture5, v_DetailMapCoord);
	#endif

	#ifdef ALBEDO_DETAIL
		diffuseColour.rgb *= detailTexture.r*2.0;
	#endif

	diffuseColour.rgb = Gamma(diffuseColour.rgb);

#endif//FLAT_COLOUR

#if defined(SEPARATE_ALPHA)
	// Using the R channel because we assume the alpha texture to be grayscale
	lowp vec4 alphaTexture = texture2DWithBias(s_Texture4, v_TexCoord2);
	diffuseColour.a = alphaTexture.r;
#endif

#if defined(VERTEX_ALPHA)
	// Using vertex colour A to alpha
	lowp vec4 vertexAlpha = v_VertexColour;
	diffuseColour.a *= 1.0-vertexAlpha.r;
#endif

	///////////////////////////////////////////////// Gloss and Spec

#if defined(GLOSS_MAP) || defined(NIGHT_GLOW) || defined(GLOW) || defined(METALLIC_MAP)
	lowp vec4 glossTexture = texture2DWithBias(s_Texture3, v_TexCoord0);
#elif defined(WORLD_GLOSS_MAP)
	#define GLOSS_MAP // From here on out everything is the same as local-space gloss map
	lowp vec4 glossTexture = texture2DWithBias(s_Texture3, v_WorldGlossMapCoord);
#endif

#if defined(WET)
	highp vec3 wetTint = mu_WetTint;
#endif

#if defined(METALLIC_MAP)
	lowp float metallic = glossTexture.b;
	highp vec3 spec = mix(vec3(0.04), diffuseColour.rgb, metallic);
	diffuseColour.rgb *= (1.0 - metallic);
	#if defined(WET)
		wetTint = mix(wetTint, vec3(1.0), metallic);
	#endif
#elif defined(SPECULAR_MAP)
	highp vec3 spec = Gamma(texture2DWithBias(s_Texture6, v_TexCoord0).rgb);
#else
	highp vec3 spec = mu_Spec;
#endif

#ifdef GLOSS_MAP
	highp float gloss = glossTexture.r;
#else
	highp float gloss = mu_Gloss;
#endif

#ifdef GLOSS_DETAIL
	lowp float glossDetail = detailTexture.g;
	gloss += glossDetail;
#endif

	///////////////////////////////////////////////// Normal

	//highp vec3 N_W = normalize(v_Normal_W);
	highp vec3 N_W = vec3(0, 1, 0);

#ifdef NORMAL_MAP
	#ifdef NORMAL_SCALE
		highp vec3 N = NormalMap(s_Texture2, v_TexCoord0 * mu_NormalScale, v_Tangent_W, v_Bitangent_W, N_W);
	#else
		highp vec3 N = NormalMap(s_Texture2, v_TexCoord0, v_Tangent_W, v_Bitangent_W, N_W);
	#endif

#elif defined(WORLD_NORMAL_MAP)
	#define NORMAL_MAP // From here on out everything is the same as tangent-space normal map
	const highp float balancedNormalScale = 2.007874; // 255/254 * 2
	highp vec3 N_T = texture2D(s_Texture2, v_DetailMapCoord).rgb * balancedNormalScale - 1.0;
	highp vec3 N = normalize(vec3(N_T.x, 0.0, N_T.z) + N_T.y * N_W);

#elif defined(WORLD_NORMAL_MAP_UNIQUE)
	#define NORMAL_MAP // From here on out everything is the same as tangent-space normal map
	const highp float balancedNormalScale = 2.007874; // 255/254 * 2
	//highp vec3 N_T = texture2D(s_Texture2, v_TexCoord0).rgb * balancedNormalScale - 1.0;
	highp vec3 N_T = texture2D(s_Texture2, vec2(v_TexCoord0.y, v_TexCoord0.x)).rgb * balancedNormalScale - 1.0;
	highp vec3 N = normalize(vec3(N_T.x, 0.0, N_T.z) + N_T.y * N_W);
	
#else
	highp vec3 N = N_W;
#endif

#if defined(DYNAMIC_WATER)
	float waveSteepness = 0.5;
	float waveTiling = 1.0;
	float timer = u_WaveTime * 2.0 * 3.14159265;

	vec2 windDir[3];
	windDir[0] = normalize(vec2(0.8, 1.0));
	windDir[1] = normalize(vec2(-0.8, 1.0));
	windDir[2] = normalize(vec2(-0.0, 1.0));
	vec3 amplitudes = vec3(0.5, 0.8, 1.0);
	vec3 wavelengths = vec3(100.0, 90.0, 110.0);
	vec3 wavesIntensity = vec3(1.0);

	vec3 waterNormal = vec3(0.0);
	vec3 Q = waveSteepness / ((2.0 * 3.14159265 / wavelengths) * amplitudes);
	for (int j = 0; j < 3; ++j)
	{
		float A = wavesIntensity[j] * amplitudes[j];
		vec3 vals = GerstnerWaveValues(v_Pos_W.xz * waveTiling, windDir[j], A, wavelengths[j], Q[j], timer);
		waterNormal += wavesIntensity[j] * GerstnerWaveNormal(windDir[j], A, Q[j], vals);
	}
	N = normalize(waterNormal);
#endif

	///////////////////////////////////////////////// Albedo variation

#if defined(VARIATION) && defined(VERTEX_WET)

	#if defined(GLOSS_MAP) && !defined(METALLIC_MAP) // Metallness and variation are clashing on B channel
		highp float localVariation = glossTexture.b;
	#else
		highp float localVariation = 1.0;
	#endif
	
	localVariation *= v_VertexColour.b;

	// TODO: add global variation slider for the road skids
	highp float variation = localVariation;

	// Apply variation tint to albedo
	//diffuseColour.rgb *= 1.0 - variation; // For Cody: Use this if you want to just darken albedo instead
	diffuseColour.rgb = mix(diffuseColour.rgb, mu_VariationTint, variation);
#endif

	///////////////////////////////////////////////// Wetness
	
#if defined(WET)
	
	#if defined(GLOSS_MAP)
		highp float localWetness = glossTexture.g;
	#else
		highp float localWetness = mu_Wetness;
	#endif

	highp float puddleMask = 0.0;
	#if defined(VERTEX_WET)
		// Vertex paint R defines dryness that removes local wetness (e.g. under the bridge)
		localWetness *= (1.0 - v_VertexColour.r*1.04);

		// Vertex paint G defines big water puddles which override local wetness
		puddleMask = min(1.0, v_VertexColour.g * 2.0);
		localWetness = max(localWetness, puddleMask);
	#endif

	#if defined(VARIATION) && defined(PLANAR_REFLECTION) && defined(VERTEX_WET)
		// On the road, albedo variation from skids also removes wetness (max 50%)
		localWetness *= (1.0 - variation * 0.5);
	#endif

	// Combine local wetness (from texture or material uniform) with global wetness (from engine uniform)
	//highp float wetness = localWetness * u_Wetness;

	highp float wetness = 0.0;
	if (u_IsRaining == 1) // TODO: make this a shader feature to avoid branch?
	{
#if defined(DETAIL_ROAD)
		highp float raindropPattern = 1.0 - detailTexture.b;
		//highp float raindropPattern = detailTexture.b;
		
		// SVN trunk
		highp float raindropReveal = clamp((u_Wetness * 2.0 - raindropPattern) / 0.2, 0.0, 1.0);
		highp float rainProgress = mix(raindropReveal * mu_WetTintLimit, u_Wetness, u_Wetness);
		wetness = min(rainProgress, localWetness);

		// Same, but with puddles revealing instead of blending on top of raindrops
		//highp float raindropReveal = clamp((u_Wetness * 2.0 - raindropPattern) / 0.2, 0.0, 1.0);
		//highp float raindropWetness = min(raindropReveal * mu_WetTintLimit, localWetness);
		//highp float puddleReveal = 2.0 - u_Wetness* 2.0;
		//highp float puddleWetness = max(0.0, localWetness - puddleReveal );
		//wetness = max(raindropWetness, puddleWetness);
#else
		wetness = min(localWetness, u_Wetness);
#endif
	}
	else
	{
		highp float dryProgress = 1.0 - u_Wetness;
		wetness = max(0.0, localWetness - dryProgress );
	}
	
	// Porous materials get darker when wet (full darkness achieved at given limit, above that is just extra gloss)
	highp float wetTintFactor = min(1.0, wetness / mu_WetTintLimit);
	diffuseColour.rgb *= mix(vec3(1.0), wetTint, wetTintFactor);

	// Blend from dry gloss value towards shiny (water) when wet
	gloss = mix(gloss, 0.95, wetness);
	
	// Water puddles also flatten the normal
	#ifdef NORMAL_MAP
		highp float flatNRange = (1.0 - mu_WetTintLimit) * 0.5;
		highp float flatNThreshold = 1.0 - flatNRange;
		highp float flatNFactor = clamp((wetness - flatNThreshold) / flatNRange, 0.0, 1.0);
		N = mix(N, N_W, max(flatNFactor, puddleMask * u_Wetness));
	#endif

#endif

	///////////////////////////////////////////////// Lighting basis

	// Don't allow gloss to be 1.0 because GGX goes crazy
	gloss = min(gloss, 0.999);
	highp float rough = 1.0 - gloss;

	// At night, replace directional light with player headlight
#ifdef NIGHT
	highp vec3 L = normalize(u_HeadLightPos - v_Pos_W);
#else
	highp vec3 L = -u_LightDirWorldSpace;
#endif
	highp vec3 V = normalize(u_CamPos - v_Pos_W);
	
	N = normalize(N - min(0.0, dot(N,V)) * V);
	
	highp vec3 R = reflect(-V, N);

	// rotate the world space reflection dir around Y-axis to match the sky dome orientation.
	highp mat2 skyRotation = mat2(u_SkyRotation.xy, u_SkyRotation.zw);
	R.xz = skyRotation * R.xz;
	highp vec3 H = normalize(L + V);

	//highp float NdotV = max(0.0001, dot(N, V));
	highp float NdotV = max(0.0, dot(N, V));
	highp float NdotH = max(0.0, dot(N, H));
	highp float NdotL = max(0.0, dot(N, L));
	highp float LdotH = max(0.0, dot(L, H));

#if defined(CACHED_SHADOW_MAP) || defined(PLANAR_REFLECTION) || defined(PARTICLE_SHADOW)
	highp vec2 screenCoord = gl_FragCoord.xy * u_ViewportSizeInv;
#endif

#if defined(SHADOW_MAP)
	#ifdef CACHED_SHADOW_MAP
		// Retrieve cached lightmap colour via screen space coords
		mediump vec3 lightmapTexture = texture2D(s_Texture1, screenCoord).rgb;
	#else
		mediump vec3 lightmapTexture = texture2DWithBias(s_Texture1, v_TexCoord1).rgb;

		#ifdef UPDATE_CACHED_SHADOW_MAP
			#ifndef RENDER_TO_CUBEMAP
				#ifdef MT_GL_ES_3
					// Store cached lightmap colour
					gl_MultiFragColor = vec4(lightmapTexture, 1.0);
				#endif
			#endif
		#endif
	#endif
	// Apply lightmap tint, multiplier etc
	mediump vec3 lightmapColour = lightmapGammaToLinear(getColourFromLightmap(lightmapTexture));
#endif

#ifdef PARTICLE_SHADOW
	lowp float particleShadow = texture2D(u_ParticleShadowTexture, screenCoord).r;
	particleShadow = 1.0 - 0.7 * particleShadow;
#else
	lowp float particleShadow = 1.0;
#endif

	// At night, replace directional light with player headlight
#ifdef NIGHT
	highp float headLightCoeff = 0.0;
	calculateHeadLightCoeffPbr(v_PosHeadLightSpace, u_HeadLightFalloff, u_HeadLightAtten, headLightCoeff);
	#ifdef REFLECTOR
		headLightCoeff = min(headLightCoeff * 5.0, 5.5);
	#endif
	#ifdef REFLECTOR_MARKER
		headLightCoeff = min(headLightCoeff * 7.0, 5.5);
	#endif
	mediump vec3 lightColour = u_HeadLightColour * headLightCoeff;
#else
	#ifdef SHADOW_MAP
		mediump vec3 lightColour = lightmapColour;
	#else
		mediump vec3 lightColour = u_LightSpecularColour * u_PbrLightParams.x;
	#endif
#endif

#if defined(SHADOW_MAP) && !defined(NIGHT)
	// Renormalize lightmap for the new normal direction
	#ifdef NORMAL_MAP 
		highp float NWdotL = max(0.001, dot(N_W, L));
		highp float Renormalize = NdotL / NWdotL;
		lightColour *= mix(1.0, max(0.3, Renormalize), NWdotL);
	#endif

	lightColour = mix(Gamma(u_LightAmbientColour), lightColour, particleShadow) * particleShadow;
#else
	lightColour *= NdotL * particleShadow;
#endif

#ifdef SCATTERED_TRANSLUCENCY
	// Forward-Scattered Translucency
	highp float T		= pow(max(0.0, dot(V, -L)), mu_TranslucencyFalloff);

	// increase brightness and transparency to fake a translucent effect
	diffuseColour.rgb	+= diffuseColour.rgb * T;
	diffuseColour.rgb	= clamp( diffuseColour.rgb, 0.0, 1.0 );
	diffuseColour.a		= 1.0 - (T * mu_TranslucencyOpacity);
	lightColour			+= lightColour * u_TranslucencyScale * T;		
#endif

	///////////////////////////////////////////////// Direct + ambient diffuse

#ifdef DIRECT_LIGHTING
	highp vec3 diffuseLightColour = lightColour;

	// At night, lightColour is replaced with player headlight, so add the lightmap here
	#if defined(SHADOW_MAP) && defined(NIGHT)
		diffuseLightColour += lightmapColour;
	#endif
#else
	highp vec3 diffuseLightColour = vec3(0.0);
#endif

#ifdef AMBIENT_LIGHTING
	#ifndef SHADOW_MAP
		#if defined(MT_GL_ES_3) && defined(CUBE_AMBIENT) && !defined(RENDER_TO_CUBEMAP)
			mediump vec3 envIrradiance = EnvMapDiffuseToLinear(SphereMapLookup( s_pbrMap, N, MAX_PBR_MIP_LEVEL ).rgb);
			diffuseLightColour += envIrradiance;
		#else
			diffuseLightColour += Gamma(u_LightAmbientColour);
		#endif
	#endif
#endif

	highp vec3 diffuse = diffuseColour.rgb * diffuseLightColour;

	///////////////////////////////////////////////// Direct specular

	highp vec3 FS = F_Schlick(spec, LdotH);
	highp float DG = Specular_GGX(NdotH, NdotV, NdotL, gloss);
	highp vec3 directSpecular = vec3(DG) * FS;

#if defined(SHADOW_MAP) && !defined(NIGHT)
	directSpecular *= u_LightSpecularColour * u_PbrLightParams.x * NdotL * particleShadow;
	// Mask direct specular when lightmap falls below the threshold value. Because we don't have a true separate shadow map :(
	directSpecular *= clamp((Luminance(lightmapTexture) - u_PbrLightParams.y) / 0.2, 0.0, 1.0);
#else
	directSpecular *= lightColour;
#endif
	
	///////////////////////////////////////////////// Ambient specular

	highp vec3 FSG = F_SchlickGloss(spec, NdotV, gloss);

	highp vec2 envBRDF = brdf_lut( s_brdfMap, rough, NdotV );

	//highp vec3 envSpec = EnvMapSpecularToLinear(SphereMapLookup( s_pbrMap, R, GetPbrMipLevel(gloss) ).rgb);
#ifndef RENDER_TO_CUBEMAP
	//lowp vec3 envSpec = EnvMapSpecularToLinear(CubeMapLookup( s_cubeMap, R, 0.0 ).rgb);
	lowp vec3 envSpec = EnvMapSpecularToLinear(SphereMapLookupLodZero( s_waterReflection, R ).rgb);
#else
	lowp vec3 envSpec = vec3(0.0);
#endif

#if defined(WET) && defined(PLANAR_REFLECTION)

	highp vec2 planarCoord = screenCoord;
	#ifdef NORMAL_MAP
		highp vec3 NoM = N - dot(N, N_W) * N_W;
		//planarCoord.x += dot(NoM, u_CamX) * 5.0 * (1.0 - gl_FragCoord.z);
		//planarCoord.y -= dot(NoM, u_CamY) * 5.0 * (1.0 - gl_FragCoord.z);
		//planarCoord.x += dot(NoM, u_CamX) * mix(5.0, 1.0, gloss);
		//planarCoord.y -= dot(NoM, u_CamY) * mix(5.0, 1.0, gloss);
		planarCoord.x += dot(NoM, u_CamX);
		planarCoord.y -= dot(NoM, u_CamY);
	#endif
	
	lowp vec4 planarTexture = texture2D(s_PlanarReflectionTexture, planarCoord);
	planarTexture.a *= wetness;
	//planarTexture.a *= gloss * gloss;

	envSpec = mix(envSpec, Gamma(planarTexture.rgb), planarTexture.a);
	directSpecular *= 1.0 - planarTexture.a;

#endif
	
	//highp vec3 ambientSpecular = envSpec * FSG;
	highp vec3 ambientSpecular = envSpec * (spec * envBRDF.x + vec3(envBRDF.y) );
	//highp vec3 ambientSpecular = spec_monte_carlo( s_monteCarloMap, spec, rough, N, V, random );

	// Reduce down facing reflections
	ambientSpecular *= clamp(R.y / 0.2, 0.0, 1.0);
	///////////////////////////////////////////////// Final colour + Fog

#if defined(DIFFUSE_LIGHTING)
	mediump vec3 c = diffuse;
#else
	mediump vec3 c = vec3(0.0);
#endif

#if defined(SPECULAR_LIGHTING)
	#if defined(DIRECT_LIGHTING) && defined(AMBIENT_LIGHTING)
		c += directSpecular + max(vec3(0.0), vec3(1.0) - directSpecular) * ambientSpecular;
	#elif defined(DIRECT_LIGHTING)
		c += directSpecular;
	#elif defined(AMBIENT_LIGHTING)
		c += ambientSpecular;
	#endif
#endif

#if defined(NIGHT) && defined(NIGHT_GLOW)
	c += glossTexture.b * mu_NightGlowColour;
#endif

#if defined(GLOW)
	c += glossTexture.b * mu_GlowColour;
#endif

	highp float alpha = diffuseColour.a;

	// Scale the fog colour by lightmap intensity, so that bumping up the lightmap doesn't make the fog seem less thick
	#ifdef FOG
		#ifdef SUN_FOG
			c = mix( c, Gamma(v_FogColour) * u_PbrLightParams.z, v_FogFactor );
		#else
			c = mix( c, Gamma(u_FogColour) * u_PbrLightParams.z, v_FogFactor );
		#endif
	#endif

#ifdef VERTEX_COLOUR
	diffuse *= v_VertexColour.rgb;
	alpha *= v_VertexColour.a;
#endif

#ifdef ANTIALIASED_LINES
	alpha *= v_aaLineTransparency;
#endif

#ifdef DETAIL_ROAD
	//c = vec3(rainDropPattern);
#endif

	//c = vec3(directSpecular);
	//c = vec3(ambientSpecular);
	//c = vec3(1, 0, 0);
	//gl_FragColor = vec4(LinearToOutput(c), alpha);
	gl_FragColor = vec4(GammaInv(c), alpha);


}


// These are now added from mtShaderGL.cpp when compiling the source depending on device settings
//#define TONEMAP
//#define GAMMA
//#define GAMMA_2_2

#define MAX_PBR_MIP_LEVEL 5.0

const highp float PI = 3.1415927;

const highp float BLOOM_SCALE = 0.5;

highp float GetPbrMipLevel(in highp float gloss)
{
	return (1.0 - gloss*gloss) * MAX_PBR_MIP_LEVEL;
}

highp vec3 F_Schlick(in highp vec3 spec, in highp float D)
{
	highp float D5 = pow(1.0 - D, 5.0);
	return spec + (1.0-spec) * D5;
}

highp vec3 F_SchlickGloss(in highp vec3 spec, in highp float D, in highp float gloss)
{
	highp float D5 = pow(1.0 - D, 5.0);
	return spec + (max(vec3(gloss),spec) - spec) * D5;
	//return spec * (1.0 - D5) + D5 * gloss*gloss;
}

highp float D_BlinnPhong(in highp float NdotH, in highp float gloss)
{
	highp float specPow = exp2(10.0 * gloss + 1.0);		// [2,2024]
	return ((specPow + 2.0) / 8.0) * pow(NdotH, specPow);
}

highp float D_GGX(in highp float NdotH, in highp float rough)
{
	highp float a = rough * rough;
	highp float a2 = a * a;
	highp float d = (NdotH * a2 - NdotH) * NdotH + 1.0;
	return a2 / (d * d);
}

highp float G_Schlick(in highp float NdotV, in highp float NdotL, in highp float rough)
{
	highp float a = rough * rough;
	highp float k = a * 0.5;
	highp float GV = NdotV / (NdotV * (1.0 - k) + k);
	highp float GL = NdotL / (NdotL * (1.0 - k) + k);
	return GV * GL;
}

highp float Vis_Schlick(in highp float NdotV, in highp float NdotL, in highp float rough)
{
	// Microfacet BRDF = D * F * G  / (4 * NoV * NoL) = D * F * Vis
	// Vis_Schlick = G_Schlick / (4 * NoV * NoL)

	highp float a = rough * rough;
	highp float k = a * 0.5;
	highp float GV = NdotV * (1.0 - k) + k;
	highp float GL = NdotL * (1.0 - k) + k;
	return 0.25 / (GV * GL);
}

highp float G_Smith(in highp float NdotV, in highp float NdotL, in highp float rough)
{
	highp float a = rough * rough;
	highp float a2 = a * a;
	highp float GV = 2.0 * NdotV / (NdotV + sqrt((1.0 - a2) * NdotV * NdotV + a2));
	highp float GL = 2.0 * NdotL / (NdotL + sqrt((1.0 - a2) * NdotL * NdotL + a2));
	return GV * GL;
}

highp float Vis_Smith(in highp float NdotV, in highp float NdotL, in highp float rough)
{
	// Microfacet BRDF = D * F * G  / (4 * NoV * NoL) = D * F * Vis
	// Vis_Smith = G_Smith / (4 * NoV * NoL)

	highp float a = rough * rough;
	highp float a2 = a * a;
	highp float GV = NdotV + sqrt((1.0 - a2) * NdotV * NdotV + a2);
	highp float GL = NdotL + sqrt((1.0 - a2) * NdotL * NdotL + a2);
	return 1.0 / (GV * GL);
}

highp float Specular_GGX(in highp float NoH, in highp float NoV, in highp float NoL, in highp float gloss)
{
	highp float rough = 1.0 - gloss;
	highp float D = D_GGX(NoH, rough);
	highp float Vis = Vis_Schlick(NoV, NoL, rough);
	return D * Vis;
}

highp vec3 getSpecularDominantDir ( highp vec3 N , highp vec3 R , highp float roughness )
{
	highp float smoothness = clamp(1.0 - roughness, 0.0, 1.0 );
	highp float lerpFactor = smoothness * ( sqrt ( smoothness ) + roughness );
	return normalize(mix( N , R , lerpFactor ));
}

highp vec3 Gamma(in highp vec3 c)
{
#if defined(GAMMA_2_2)
	return pow(c, vec3(2.2));
#elif defined(GAMMA)
	return c * c;
#else
	return c;
#endif
}

highp float Gamma(in highp float s)
{
#if defined(GAMMA_2_2)
	return pow(s, 2.2);
#elif defined(GAMMA)
	return s * s;
#else
	return s;
#endif
}

highp vec3 GammaInv(in highp vec3 c)
{
#if defined(GAMMA_2_2)
	return pow(c, vec3(1.0/2.2));
#elif defined(GAMMA)
	return sqrt(c);
#else
	return c;
#endif
}

highp float Luminance(in highp vec3 colour)
{
	return dot(vec3(0.3, 0.59, 0.11), colour);
}

#define USE_TONEMAP_TWEAKABLES 0

#if (USE_TONEMAP_TWEAKABLES)
uniform highp vec4 u_ToneMapABCD;
uniform highp vec4 u_ToneMapEF;
#endif

highp vec3 FilmicToneMap(in highp vec3 x )
{
#if (USE_TONEMAP_TWEAKABLES)
	highp float A = u_ToneMapABCD.x;
	highp float B = u_ToneMapABCD.y;
	highp float C = u_ToneMapABCD.z;
	highp float D = u_ToneMapABCD.w;
	highp float E = u_ToneMapEF.x;
	highp float F = u_ToneMapEF.y;


#else
	highp float A = 1.07;
	highp float B = -0.03;
	highp float C = 6.47;
	highp float D = 2.48;
	highp float E = 0.54;
	highp float F = 0.27;

#endif


	return ((x*(A*x+C*B)+D*E)/(x*(A*x+B)+D*F))-E/F;
}

highp vec3 toneMapHable(in highp vec3 colour, in highp float whitepoint)
{
	return FilmicToneMap(colour) / FilmicToneMap(vec3(whitepoint));
}

highp vec3 toneMapReinhard(in highp vec3 colour, in highp float whitepoint)
{
	highp vec3 c = colour;
	return c * (vec3(1.0) + c / (whitepoint * whitepoint)) / (vec3(1.0) + c);
}

uniform highp vec4 u_HdrParams;

highp vec3 toneMap(in highp vec3 colour)
{
	highp float whitepoint = u_HdrParams.w;

#ifdef TONEMAP
	return toneMapHable(colour, whitepoint);
	//return toneMapReinhard(colour, whitepoint);
#else
	return colour;
	//TODO: do something like colour * fixed exposure / whitepoint at least? Maybe we can't afford that either.
#endif
}

highp vec3 expose(in highp vec3 colour)
{
	highp float exposure = u_HdrParams.x;
	return colour * exposure;
}

highp vec3 exposeAdapt(in highp vec3 colour, in highp float adaptedExposure)
{
	return colour * adaptedExposure;
}

// A higher bias gives us more precision in the high range but less precision in the low range,
// which introduces colour banding on gradients like a clear blue sky or reflection on a black car.
#define REINHARD_BIAS 0.3
// The limit, in combination with REINHARD_BIAS, defines the max possible range we will clamp to.
// I chose this value to match the linear-space range of 36 in our RGBM encoding
// E.g. 0.992 * 0.3 / (1 - 0.992) = 37.2
#define REINHARD_LIMIT 0.992

highp vec3 reinhardEncodeGamma(in highp vec3 colour)
{
	highp vec3 c = Gamma(colour);
	return c / (c + vec3(REINHARD_BIAS));
}

highp vec3 reinhardEncode(in highp vec3 colour)
{
	highp vec3 c = colour;
	return c / (c + vec3(REINHARD_BIAS));
}

highp vec3 reinhardDecode(in highp vec3 colour)
{
	// The limit should be applied here rather than during encoding,
	// to avoid division by zero in case of unencoded values in the framebuffer
	highp vec3 c = min(colour, vec3(REINHARD_LIMIT));
	return c * REINHARD_BIAS / (vec3(1.0) - c);
}

// The range here must match the one defined in the tools/fmTexTools project,
// which is used when processing EXR assets!
#define RGBM_RANGE 6.0

highp vec4 encodeRGBM(in highp vec3 c)
{
	highp vec3 cN = min(GammaInv(c) / RGBM_RANGE, vec3(1.0));
	highp float cMax = max(cN.r, max(cN.g, cN.b));
	highp float m = ceil(cMax * 255.0) / 255.0;
	return vec4(cN / m, m);
}

highp vec3 decodeRGBM(in highp vec4 rgbm)
{
	return Gamma(RGBM_RANGE * rgbm.rgb * rgbm.a);
}

const highp vec4 bitSh = vec4(
	16777216.0,	// 256*256*256
	65536.0,	// 256*256
	256.0,
	1.0);

const highp vec4 bitShInv = vec4(
	1.0 / 16777216.0,
	1.0 / 65536.0,
	1.0 / 256.0,
	1.0);

const highp vec4 bitMsk = vec4(
	0.0,
	0.00390625, // 1/256
	0.00390625,
	0.00390625);

highp vec4 floatToRgba(highp float value)
{
	highp vec4 res = fract(value * bitSh);
	res -= res.xxyz * bitMsk;
	return res;
}

highp float rgbaToFloat(highp vec4 value)
{
	return(dot(value, bitShInv));
}

#ifdef MT_FRAGMENT_SHADER

highp vec3 NormalMap(in lowp sampler2D tex, in highp vec2 texCoord, in highp vec3 v_T, in highp vec3 v_B, in highp vec3 N)
{
	highp mat3 T_to_W = mat3(v_T, v_B, N);
	highp vec3 N_T = texture2DWithBias(tex, texCoord).rgb * 2.0 - vec3(1.0);
	return normalize(T_to_W * N_T);
}

#ifdef DOESNT_COMPILE
// texture2DLod complains on some drivers, Ivan reckons we need to declare the shader as version 3 to fix it.
// Function currently unused, make sure you test Adreno if you want to use it!

mediump vec3 SphereMapLookup( in mediump sampler2D tex, in highp vec3 R, in highp float lod)
{
	highp vec3 R_Sphere = R;
	R_Sphere.z = -R_Sphere.z;
	highp vec3 N_Sphere = normalize(R_Sphere + vec3(0.0,1.0,0.0));
	highp vec2 UV = vec2(N_Sphere.x, N_Sphere.z) * 0.5 + vec2(0.5);

	#ifdef MT_GL_ES_3
		return texture2DLod( tex, UV, lod ).rgb;
	#else
		return texture2D( tex, UV ).rgb;
	#endif
}
#endif


mediump vec3 SphereMapLookupLodZero( in mediump sampler2D tex, in highp vec3 R)
{
	highp vec3 R_Sphere = R;
	R_Sphere.z = -R_Sphere.z;
	highp vec3 N_Sphere = normalize(R_Sphere + vec3(0.0,1.0,0.0));
	highp vec2 UV = vec2(N_Sphere.x, N_Sphere.z) * 0.5 + vec2(0.5);
	return texture2D( tex, UV ).rgb;
}

mediump vec3 CubeMapLookup( in mediump samplerCube tex, in highp vec3 R, in highp float lod)
{
	highp vec3 R_Cube = R;
	R.xy = -R.xy;
	return textureCube( tex, R ).rgb;
}

highp vec2 brdf_lut( highp sampler2D brdfMap, highp float rough, highp float NoV)
{
	// Sample precomputed brdf_monte_carlo from a lookup texture.
	// Scale and bias half pixel inwards to align 0.0 and 1.0 to centre of edge pixels.
	// The magic numbers must match size of mtCubeMapManager::m_pbrBrdfTex
	highp vec2 uv = vec2(NoV, rough) * 0.9921875 + vec2(0.00390625);
	return texture2D(brdfMap, uv).rg; 
}

mediump vec3 EnvMapSpecularToLinear( in mediump vec3 envMap )
{
#if defined(HDR_ENCODED_ENV)
	return reinhardDecode(envMap);
#elif defined(HDR_LINEAR_ENV)
	return envMap;
#else
	return Gamma(envMap);
#endif
}

mediump vec3 EnvMapDiffuseToLinear( in mediump vec3 envMap )
{
#if defined(HDR_ENCODED_ENV)
	return reinhardDecode(envMap);
#elif defined(HDR_LINEAR_ENV)
	return envMap;
#else
	return Gamma(envMap);
#endif
}

mediump vec3 LinearToOutput( in highp vec3 c)
{
#if defined(HDR_ENCODE)
	return reinhardEncode(c);
#elif defined(HDR_LINEAR)
	return c;
#elif defined(RENDER_TO_CUBEMAP)
	return GammaInv(c);
#else
	return GammaInv(toneMap(c));
#endif
}

mediump vec3 GammaToOutput( in highp vec3 c)
{
#if defined(HDR_ENCODE)
	return reinhardEncodeGamma(c);
#elif defined(HDR_LINEAR)
	return Gamma(c);
#elif defined(RENDER_TO_CUBEMAP)
	return c;
#else
	return toneMap(c);
#endif
}

#endif//MT_FRAGMENT_SHADER

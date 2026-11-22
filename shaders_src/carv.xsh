//
//  car.vsh
//
//  Created by bend on 10/07/12.
//  Copyright Electronic Arts 2012. All rights reserved
//

//%0define USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
//%1define USE_SHADOW_MAP
//%2define DISABLE_CUBE_MAP
//%3define CAR_CROSSFADE_PASS_1
//%4define CAR_CROSSFADE_PASS_2
//%5define CAR_WHEEL_CROSSFADE_PASS_1
//%6define CAR_WHEEL_CROSSFADE_PASS_2
//%7define CAR_DISCARDWIPE_PASS_1
//%8define CAR_DISCARDWIPE_PASS_2

// TODO: We might need to do double SH calculation, one for track lights occluded by the shadow map,
// another one for extra stuff like car headlights without the shadow map applied to the result
//%9define USE_SH_LIGHTING

//%10define USE_SH_LIGHTING
//%10define DISABLE_CUBE_MAP

//%11define USE_SH_LIGHTING
//%11define DISABLE_CUBE_MAP
//%11define DIFFUSE_LIGHTING

//%12define USE_SHADOW_MAP
//%12define SPHERICAL_CUBE_MAP_BLUR

//%13define USE_SH_LIGHTING
//%13define SPHERICAL_CUBE_MAP_BLUR

//////////////////////////////////////////////// NEW FEATURES SYSTEM
//%feature FOG
//%feature SUN_FOG
//%feature SINGLE_SPEC
//%feature DOUBLE_SPEC
//%feature CUBE_MAP
//%feature SPHERICAL_CUBE_MAP_BLUR
//%feature USE_SH_LIGHTING
//%feature USE_SHADOW_MAP
//%feature USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW
//%feature CAR_CROSSFADE_PASS_1
//%feature CAR_CROSSFADE_PASS_2
//%feature CAR_WHEEL_CROSSFADE_PASS_1
//%feature CAR_WHEEL_CROSSFADE_PASS_2
//%feature CAR_DISCARDWIPE_PASS_1
//%feature CAR_DISCARDWIPE_PASS_2
//%feature DIFFUSE_LIGHTING
//%feature ALPHA_MODULATE
//%feature SPEC_TEXTURE
//%feature LIGHTS
//%feature LED_LIGHTS
//%feature SPEC_MASK_TEXTURE
//%feature REF_TEXTURE_MASK
//%feature COLOURED_FRESNEL
//%feature TIRES
//%feature TIRE_INNER_RADIUS_SCALE
//%feature WHEEL_BLUR
//%feature ROTOR_GLOW
//%feature GLASS
//%feature SPEC_MASK_IN_ALPHA
//%feature ARMS
//%feature NORMAL_MAPPED
//%feature SPEC_FLAKES
//%feature ANIMATED_NASCAR_NET			

//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, [ALPHA_MODULATE]
//%precompile FOG, SUN_FOG, USE_SHADOW_MAP, CUBE_MAP, [ALPHA_MODULATE]
//%precompile FOG, SUN_FOG, USE_SH_LIGHTING, CUBE_MAP, [ALPHA_MODULATE]
//%precompile FOG, SUN_FOG, USE_SH_LIGHTING, [ALPHA_MODULATE]
//%precompile FOG, SUN_FOG, [ALPHA_MODULATE]
//%precompile FOG, [ALPHA_MODULATE]

//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, CAR_CROSSFADE_PASS_1
//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, CAR_CROSSFADE_PASS_2
//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, CAR_WHEEL_CROSSFADE_PASS_1
//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, CAR_WHEEL_CROSSFADE_PASS_2
//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, CAR_DISCARDWIPE_PASS_1
//%precompile FOG, SUN_FOG, USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW, CUBE_MAP, CAR_DISCARDWIPE_PASS_2
//
//%include utility.xsh

#if defined(USE_SH_LIGHTING) && defined(LED_LIGHTS)
	#undef USE_SH_LIGHTING
#endif

#if defined(CUBE_MAP) && defined(DISABLE_CUBE_MAP)
	#undef CUBE_MAP
#endif

#if defined (ANIMATED_NASCAR_NET)
	uniform highp vec4 u_flappyNetCentre2;
	uniform highp vec4 u_flappyNetCentre;
	uniform highp vec2 u_flappyNetCounter;
#endif

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec3 a_Normal;		//%attributeID MT_NORMAL
attribute mediump vec2 a_TexCoord0;	//%attributeID MT_UV_0

// Transformation Matrices
uniform highp mat4 u_ModelToProj;
uniform highp mat4 u_ModelToWorld;

// Light info
uniform highp vec3 u_EyePosModelSpace;

#if defined(USE_SH_LIGHTING)
	uniform mediump vec4 u_SHLightCoeffs[7];
	uniform lowp vec3 u_SHSpecColour;
	#define u_SPEC_COLOUR u_SHSpecColour
	uniform highp vec3 u_SHSpecDir;
	#define u_LIGHT_DIR_MODEL_SPACE u_SHSpecDir
#else
	uniform lowp vec3 u_LightSpecularColour;
	#define u_SPEC_COLOUR u_LightSpecularColour
	uniform highp vec3 u_LightDirModelSpace;
	#define u_LIGHT_DIR_MODEL_SPACE u_LightDirModelSpace
#endif

#if defined(USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW)
	uniform mediump vec3 u_LightDiffuseColourTimesScaleFactor;
#else
	uniform mediump vec3 u_LightDiffuseColour;
#endif

#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2)
	uniform highp float u_CarCrossfade;
#endif

varying mediump vec2 v_TexCoord0;
varying lowp vec3 v_DiffuseColour;

//varying highp vec2 v_NdotH;
varying highp vec3 v_VertexNormalModelSpace;
varying highp vec3 v_HalfVectorModelSpace;

#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	varying highp vec3 v_CrossfadePos;
#endif
#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2) || defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	varying highp float v_CrossfadeFactor;
	uniform highp vec3 u_CarCrossfadePos;
#endif

/*#ifdef SPEC_FLAKES
varying mediump vec2 v_SpecFlakesUV;
#endif*/

#ifdef FOG
	#ifdef SUN_FOG
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogColour;

		uniform highp vec3 u_FogSunParams; // (start, factor, saturation)
		uniform lowp vec3 u_FogSunColour;
		uniform highp float u_FogSunPower;
	
		varying lowp vec4 v_FogColour_Factor;		// .rgb is the color, .a is the factor
		//varying lowp float v_FogFactor;
	#else
		uniform highp vec3 u_FogParams; // (start, factor, saturation)
		varying lowp float v_FogFactor;
	#endif
#endif

#ifdef SINGLE_SPEC
	uniform lowp vec3 mu_MaterialSpecularColour;
	varying lowp vec3 v_SpecularColour;
#endif

#ifdef DOUBLE_SPEC
	uniform lowp vec3 mu_MaterialSpecularColour_Base;
	uniform lowp vec3 mu_MaterialSpecularColour_Top;
	varying lowp vec3 v_SpecularColour_Base;
	varying lowp vec3 v_SpecularColour_Top;
#endif

#ifdef CUBE_MAP
	uniform highp mat3 u_NormalToViewRotMatrix;
	varying mediump float v_ReflectionWorldSpaceYAxis;
	uniform highp vec4 u_SkyRotation; // Packed Y-Axis rotation matrix of the sky dome. mat2(u_SkyRotation.xy, u_SkyRotation.zw)

#ifdef SPHERICAL_CUBE_MAP_BLUR
	varying mediump vec2 v_SphereUV;
#else
	varying mediump vec3 v_CubeRay;
#endif
#endif

#ifdef USE_SHADOW_MAP
	uniform highp mat4 u_ModelToShadow;
	varying mediump vec2 v_ShadowUV;
#endif

#if defined(TIRE_INNER_RADIUS_SCALE) || defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2)
	// x - tyre outside inner radius
	// y - tyre inside inner radius
	// z - tyre outer radius
	// w - tyre median
	uniform highp vec4 u_TyreGeometry;

	// x - inside tyre ratio
	// y - outside tyre ratio
	// z - unused
	// w - unused
	uniform highp vec4 u_TyreRatio;
#endif

varying mediump vec2 v_EdotN;

const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );


void main()
{
	// Texture coords
	mediump vec2 texUV = a_TexCoord0 * uvMult;
	v_TexCoord0 = texUV;

	/*#ifdef SPEC_FLAKES
		v_SpecFlakesUV = (texUV * 40.0) + u_EyePosModelSpace.xy;
	#endif*/

	// Normal in model space
	v_VertexNormalModelSpace = a_Normal;


	highp vec3 vertexPosition = a_Position;

	#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
		v_CrossfadePos = vertexPosition;

		highp vec4 vPointWorldPos	= u_ModelToWorld * vec4(vertexPosition, c_one) ;
		highp vec3 vPointLocal		= vPointWorldPos.xyz - u_CarCrossfadePos;

		// want the zaxis only
		highp float nLocalZ = dot(vPointLocal, u_ModelToWorld[2].xyz);

		v_CrossfadeFactor	= clamp(( 0.5 + (nLocalZ / 20.0) ) , 0.0, 1.0);

	#endif


#if defined (ANIMATED_NASCAR_NET)
	highp float deformationAmount	= 0.1;
	highp float flappiness			= u_flappyNetCounter.y;

	highp vec4 worldPosition		= u_ModelToWorld * vec4(vertexPosition, c_one) ;
	
	// Two spheres define the flappable region. 
	highp vec3 vPointLocal1				= worldPosition.xyz - u_flappyNetCentre.xyz;			
	highp vec3 vPointLocal2				= worldPosition.xyz - u_flappyNetCentre2.xyz;
	mediump float invSphereSizeSqrd1	= u_flappyNetCentre.w;
	mediump float invSphereSizeSqrd2	= u_flappyNetCentre2.w;

	// get distance from vertex to sphere centre, clamp from 0 - 1
	// flap will be scaled by ths value to control where the mesh animates.
	highp float scaledDist1			= min( dot(vPointLocal1,vPointLocal1)	*	invSphereSizeSqrd1,	1.0 );
	highp float scaledDist2			= min( dot(vPointLocal2,vPointLocal2)	*	invSphereSizeSqrd2,	1.0 );

	// Chose the sphere thats the closest
	highp float scaledDist			= min( scaledDist2, scaledDist1 );
	highp float animScale			= 1.0 - scaledDist;
	
	vertexPosition.x += flappiness * animScale * ( sin( vertexPosition.x * deformationAmount + u_flappyNetCounter.x ) );     
#endif



	// Vector from the vertex to the eye in model space
	highp vec3 vertexToEyeModelSpace = normalize( u_EyePosModelSpace - vertexPosition );

	// Half vector
	// (Don't need to normalize here - do it per pixel anyway)
	v_HalfVectorModelSpace = u_LIGHT_DIR_MODEL_SPACE + vertexToEyeModelSpace;

	// N dot H (for looking up the spec value from the spec texture)
	//v_NdotH = vec2( max( 0.001, dot( a_Normal, v_HalfVectorModelSpace ) ), c_zero );

	// E dot N (for looking up the fresnel term from the fresnel texture)
	v_EdotN = vec2( c_one - max( c_zero, dot( vertexToEyeModelSpace, a_Normal ) ), c_zero );

	// N dot L
	highp float ndotl = max( c_zero, dot( a_Normal, u_LIGHT_DIR_MODEL_SPACE ));



	// Diffuse
#ifdef USE_SH_LIGHTING
	mediump vec3 n = normalize((u_ModelToWorld * vec4(a_Normal, 0.0)).xyz);
	mediump vec4 vA = vec4(n, 1.0);
	mediump vec3 x1 = vec3(dot(u_SHLightCoeffs[0], vA), dot(u_SHLightCoeffs[1], vA), dot(u_SHLightCoeffs[2], vA));
	mediump vec4 vB = n.xxyz * n.yzzz;
	mediump vec3 x2 = vec3(dot(u_SHLightCoeffs[3], vB), dot(u_SHLightCoeffs[4], vB), dot(u_SHLightCoeffs[5], vB));
	mediump vec3 vC = vec3(n.x*n.x - n.y*n.y);
	mediump vec3 x3 = u_SHLightCoeffs[6].rgb * vC;
	v_DiffuseColour = (x1 + x2 + x3);
#else
	#if defined(USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW)
		v_DiffuseColour = (ndotl * u_LightDiffuseColourTimesScaleFactor);
	#else
		v_DiffuseColour = (ndotl * u_LightDiffuseColour);
	#endif
#endif

	// Specular
#ifdef SINGLE_SPEC
	v_SpecularColour = u_SPEC_COLOUR * mu_MaterialSpecularColour;
#endif

#ifdef DOUBLE_SPEC
	v_SpecularColour_Base = u_SPEC_COLOUR * mu_MaterialSpecularColour_Base;
	v_SpecularColour_Top = u_SPEC_COLOUR * mu_MaterialSpecularColour_Top;
#endif
	
	// Cube map reflection
#ifdef CUBE_MAP
	highp vec3 R = reflect( -vertexToEyeModelSpace, a_Normal );
	mediump vec3 RW = (u_ModelToWorld * vec4(R, 0.0)).xyz; //ILeben: don't use mat3(mat4), it seems to have problems on Android!

	// rotate the world space reflection dir around Y-axis to match the sky dome orientation.
	highp mat2 skyRotation = mat2(u_SkyRotation.xy, u_SkyRotation.zw);
	RW.xz = skyRotation * RW.xz;

	#ifdef SPHERICAL_CUBE_MAP_BLUR
		RW.z = -RW.z;
		mediump vec3 N = normalize(normalize(RW) + vec3(0.0,1.0,0.0));
		v_SphereUV = vec2(N.x, N.z) * 0.5 + vec2(0.5);
	#else
		RW.xy = -RW.xy;
		v_CubeRay = RW;
	#endif
	v_ReflectionWorldSpaceYAxis = normalize( (u_ModelToWorld * vec4(R, 0.0)).rgb ).y;
#endif

#ifdef USE_SHADOW_MAP
	v_ShadowUV = (u_ModelToShadow * vec4( vertexPosition, c_one )).xz;
#endif

	// Position
#if defined(TIRE_INNER_RADIUS_SCALE) || defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2)
	highp float fDefaultTyreOuterRadius = u_TyreGeometry.z;
#endif

#if defined(TIRE_INNER_RADIUS_SCALE)
    highp float fTyreVertexRadiusBlend;
    highp vec4 pos = tyreInnerRadiusScale(u_ModelToProj, vertexPosition, u_TyreGeometry, u_TyreRatio, fTyreVertexRadiusBlend);

	#if defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2)
		v_CrossfadeFactor = clamp(fTyreVertexRadiusBlend, 0.0, 1.0);
	#endif
#else
	highp vec4 pos = u_ModelToProj * vec4( vertexPosition, c_one );
	#if defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2)
		v_CrossfadeFactor = clamp(length(vertexPosition.yz) / fDefaultTyreOuterRadius, 0.0, 1.0);
	#endif
#endif
	
#ifdef FOG
	#ifdef SUN_FOG
		highp float sunFogFactor = clamp(dot(u_LIGHT_DIR_MODEL_SPACE, normalize(vertexPosition - u_EyePosModelSpace)), 0.0, 1.0);
		sunFogFactor = pow(sunFogFactor, u_FogSunPower);
		highp vec3 fogParams = mix(u_FogParams, u_FogSunParams, sunFogFactor);

		// Increase with distance up to max saturation
		v_FogColour_Factor.a = clamp( (pos.w - fogParams.x) * fogParams.y, 0.0, fogParams.z );
		v_FogColour_Factor.rgb = mix(u_FogColour, u_FogSunColour, sunFogFactor);
	#else
		v_FogFactor = clamp( (pos.w - u_FogParams.x) * u_FogParams.y, 0.0, u_FogParams.z );
	#endif
#endif





	gl_Position = pos;
}


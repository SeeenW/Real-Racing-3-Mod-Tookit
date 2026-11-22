//
//  car.fsh
//
//  Created by bend on 10/07/12.
//  Copyright Electronic Arts 2012. All rights reserved.

#if defined(CUBE_MAP) && defined(DISABLE_CUBE_MAP)
	#undef CUBE_MAP
#endif

precision highp float;

const lowp float c_zero = 0.0;
const lowp float c_one = 1.0;

// Texture samplers
uniform lowp sampler2D s_Texture0;			// Base texture

#ifdef CUBE_MAP
	uniform lowp float u_FresnelFeedbackScale;
	uniform lowp float u_ReflectionContrast;
	uniform lowp float u_GlassFresnelFeedbackScale;
#endif

#if defined(USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW)
	uniform lowp float u_LightDiffuseScaleFactor;
#endif
uniform lowp vec3 u_LightAmbientColour;

#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2) || defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	uniform highp float u_CarCrossfade;
#endif

varying mediump vec2 v_TexCoord0;
//varying highp vec2 v_NdotH;
varying lowp vec3 v_DiffuseColour;

varying highp vec3 v_VertexNormalModelSpace;
varying highp vec3 v_HalfVectorModelSpace;

#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	varying highp vec3 v_CrossfadePos;
#endif
#if defined(CAR_CROSSFADE_PASS_1) || defined(CAR_CROSSFADE_PASS_2) || defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	varying highp float v_CrossfadeFactor;
#endif

#ifdef GLASS
	const lowp float c_cubemultiplier = 1.0;
#endif

#ifdef LIGHTS
	const mediump float c_diffuseMult = 3.5;
#endif

#ifdef CUBE_MAP
#ifdef SPHERICAL_CUBE_MAP_BLUR
	uniform lowp sampler2D s_Texture1;				// Spherical map
	varying mediump vec2 v_SphereUV;
#else
	uniform lowp samplerCube s_cubeMap;			// Cube map
	varying mediump vec3 v_CubeRay;
#endif
	varying mediump float v_ReflectionWorldSpaceYAxis;
#endif

#ifdef NORMAL_MAPPED
uniform lowp sampler2D s_Texture2;			// Normal map
#endif

/*#ifdef SPEC_FLAKES
uniform lowp sampler2D s_Texture2;			// Noise texture
varying mediump vec2 v_SpecFlakesUV;
#endif*/

uniform lowp sampler2D s_Texture3;			// Fresnel (rgb) and spec (a) texture
varying mediump vec2 v_EdotN;

#if defined (NORMAL_MAPPED)
uniform mediump vec3 u_LightDirViewSpace;
#endif

#ifdef SINGLE_SPEC
	uniform mediump float mu_MaterialSpecularPower;
	varying lowp vec3 v_SpecularColour;
#endif

#ifdef DOUBLE_SPEC
	uniform mediump float mu_MaterialSpecularPower_Base;
	uniform mediump float mu_MaterialSpecularPower_Top;
	varying lowp vec3 v_SpecularColour_Base;
	varying lowp vec3 v_SpecularColour_Top;
#endif

#if defined(SPEC_MASK_TEXTURE) || defined(REF_TEXTURE_MASK)
	uniform lowp sampler2D s_SpecMaskTexture; // mask texture
#endif

#if defined(SPEC_TEXTURE)
	uniform lowp vec3 u_LightSpecularColour;
#endif

#ifdef SPEC_TEXTURE
	// Note that this will conflict with the MASK texture below, but that doesn't seem to be enabled anywhere at the moment.
	// So i'm leaving it there so if it ever does get turned back on, it'll have to be fixed and set to a different
	// texture unit.
	uniform lowp sampler2D s_Texture4;	// spec texture
#endif

#ifdef USE_SHADOW_MAP
	uniform lowp sampler2D s_CarShadowMapTexture;
	varying lowp vec2 v_ShadowUV;
	uniform lowp vec3 u_ShadowChannel;
#endif

#if defined(CUBE_MAP) || defined(USE_SHADOW_MAP)
	// This is used to scale or bias the shadow and reflection colours/instensity depending on time-of-day
	uniform lowp vec3 u_CarTimeOfDayParams;
#endif

#ifdef ROTOR_GLOW
	// brake disc glow texture
	uniform lowp sampler2D s_Texture6;
	uniform lowp vec2 u_RotorGlow; 
	// x = step-ref
	// y = modulate
#endif

#ifdef DIRT //the dirt currently fights with the mask for texture unit 7, if you want to enable dirt, you should free another texture unit for it (e.g. merge fresnel ramp with spec ramp)
	//uniform lowp sampler2D s_Texture7; // dirt overlay
	//uniform lowp float u_DirtFactor; // dirt reveal factor
#endif

#ifdef FOG
	#ifdef SUN_FOG
		varying lowp vec4 v_FogColour_Factor;
		//varying lowp float v_FogFactor;
	#else
		uniform lowp vec3 u_FogColour;
		varying lowp float v_FogFactor;
	#endif
#endif

#ifdef ALPHA_MODULATE
	uniform lowp float u_AlphaModulate;
#endif

#ifdef TIRES
	uniform lowp vec3 u_TyreColour;
#endif

#if defined(WHEEL_BLUR)
	uniform lowp float u_WheelBlur;
#endif

void main()
{
#if defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	// Radial wipe for wheels
	#if defined(CAR_WHEEL_CROSSFADE_PASS_2) || defined(CAR_DISCARDWIPE_PASS_2)
		if (u_CarCrossfade < v_CrossfadeFactor)
		{
			discard;
		}
	#else
		if (v_CrossfadeFactor < u_CarCrossfade)
		{
			discard;
		}
	#endif
#endif

	highp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );

#ifdef DIRT //the dirt currently fights with the mask for texture unit 7, if you want to enable dirt, you should free another texture unit for it (e.g. merge fresnel ramp with spec ramp)
	//lowp vec4 dirtTexture = texture2DWithBias( s_Texture7, v_TexCoord0 );
#endif

#if defined(SPEC_MASK_TEXTURE) || defined(REF_TEXTURE_MASK)
	highp vec4 maskTexture = texture2D( s_SpecMaskTexture, v_TexCoord0 );
#endif

#ifdef CUBE_MAP

#ifdef SPHERICAL_CUBE_MAP_BLUR
	highp vec3 cubeHighRes = texture2D( s_Texture1, v_SphereUV ).rgb;
#else
	highp vec3 cubeHighRes = textureCube( s_cubeMap, v_CubeRay ).rgb;
#endif

	#if defined(USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW)
		cubeHighRes *= min(u_LightDiffuseScaleFactor + 0.15, 1.0);  // less reflection when in shadow
	#endif

	highp vec4 fresnelTexture = texture2D( s_Texture3, v_EdotN );

	#if defined(USE_SH_LIGHTING)
		fresnelTexture += u_CarTimeOfDayParams.x;
		cubeHighRes *= u_CarTimeOfDayParams.y;
	#endif

	// Decals are baked into the green channel of the mask, to swap the coloured fresnel term with a grayscale version of it so it doesn't affect the
	// colour of the decal. Max(r,Max(g,b)) would be technically more correct, but it gives it too much of a chrome look, and runs slower than simple average.
	#if defined(SPEC_MASK_TEXTURE) && defined(COLOURED_FRESNEL)
		highp vec3 fresnelTerm = mix(fresnelTexture.rgb, vec3(fresnelTexture.a), maskTexture.g);
	#else
		highp vec3 fresnelTerm = fresnelTexture.rgb;
	#endif

	// Using the inverse of blue channel, as requested by Jesse, so nothing changes until artists start modifying it
	#ifdef REF_TEXTURE_MASK
		fresnelTerm *= (1.0 - maskTexture.b);
	#endif
#endif

	// Per vertex spec read from texture
	//lowp float specTerm = texture2D( s_Texture3, v_NdotH ).a;
	//lowp vec3 specular = v_SpecularColour_Base * specTerm;

#if defined(SINGLE_SPEC) || defined(DOUBLE_SPEC) || defined(SPEC_TEXTURE)
	// Per pixel spec, calculated
	highp vec3 normal = normalize( v_VertexNormalModelSpace );
	highp vec3 halfVector = normalize( v_HalfVectorModelSpace );
#endif

#ifdef SINGLE_SPEC
	lowp vec3 specular = v_SpecularColour * halfAngleSpecular( halfVector, normal, mu_MaterialSpecularPower );
#endif

#ifdef DOUBLE_SPEC
	highp float tmpDot = max( 0.0, dot( normal, halfVector ) );
	lowp vec3 specularBase = v_SpecularColour_Base * pow( tmpDot, mu_MaterialSpecularPower_Base );
	lowp vec3 specularTop = v_SpecularColour_Top * pow( tmpDot, mu_MaterialSpecularPower_Top );
	lowp vec3 specular = specularBase + specularTop;
#endif

#ifdef SPEC_TEXTURE
	highp float ndoth = dot( normal, halfVector );
	ndoth = clamp( ndoth * ndoth, 0.1, 0.999 );
	highp vec3 specular = u_LightSpecularColour * texture2D( s_Texture4, vec2( ndoth, 0.0 ) ).rgb;

	#ifdef SPEC_MASK_TEXTURE
		specular *= maskTexture.r;
	#endif
#endif

#if defined(WHEEL_BLUR)
	// Make the wheel blur more transparent depending on lighting conditions. 
	const mediump vec3 luminanceWeighting = vec3( 0.2125, 0.7154, 0.0721 );
	lowp float ambientBrightness = dot( u_LightAmbientColour, luminanceWeighting );
	#if defined(SINGLE_SPEC) || defined(DOUBLE_SPEC) || defined(SPEC_TEXTURE)
		lowp float specBrightness = dot ( specular, luminanceWeighting );
	#else
		lowp float specBrightness = 0.0;
	#endif
	lowp float ambientWheelBlur = 1.0 - min(1.0, 2.0*ambientBrightness);
	lowp float specWheelBlur = min(1.0, 3.0*specBrightness);
	diffuseTexture.a = pow(diffuseTexture.a, 4.0 * (0.25 + 0.75*u_WheelBlur) * max(0.0, ambientWheelBlur - specWheelBlur) + 1.0);
#endif

#ifdef USE_SHADOW_MAP
	highp float shadowMap = dot( texture2DWithBias( s_CarShadowMapTexture, v_ShadowUV ).rgb, u_ShadowChannel );
	shadowMap = min( 1.0, shadowMap + u_CarTimeOfDayParams.z );
	shadowMap *= shadowMap * shadowMap * shadowMap;
#else
	lowp float shadowMap = 1.0;
#endif

#if defined(SINGLE_SPEC) || defined(DOUBLE_SPEC) || defined(SPEC_TEXTURE)
	#if defined(USE_DIFFUSE_SCALE_FACTOR_FOR_SHADOW)
		specular *= u_LightDiffuseScaleFactor;		// less spec when in shadow
	#elif defined(USE_SHADOW_MAP)
		specular *= clamp(5.0*pow(shadowMap,7.0), 0.0, 1.0); // Reduce spec in shadow, but keep strong outside of shadow, even on a cloudy day.
	#endif
#endif

// Diffuse colour
#if defined(LIGHTS)//MULTIUPLIE FOR BRAKES
	lowp vec3 diffuse = vec3(2.0);
#elif defined(LED_LIGHTS)//MULTIUPLIE FOR LCD and illuminated numbers
	lowp vec3 diffuse = vec3(1.15);
#elif defined(NORMAL_MAPPED)
	// Use normal from texture to intensify diffuse color
	lowp vec3 normalMapTexture = texture2DWithBias( s_Texture2, v_TexCoord0 ).rgb;
	mediump vec3 mapNormal = scaleAndBiasNormal( normalMapTexture.rgb );
	mediump float diffuseIntensity = dot( mapNormal, -u_LightDirViewSpace );
	highp vec3 diffuse = diffuseIntensity * v_DiffuseColour + u_LightAmbientColour;
#else
	highp vec3 diffuseColour = shadowMap*v_DiffuseColour;
	highp vec3 diffuse = diffuseColour + u_LightAmbientColour;
#endif

	/*#ifdef SPEC_FLAKES
		//lowp float n = fract( (v_TexCoord0.x * 13.0 + v_TexCoord0.y * 79.0) * 43758.5453 );
		//mediump vec3 noise = n * 2.0 - 1.0;
		mediump vec3 noise = texture2D( s_Texture2, v_SpecFlakesUV ).rgb;
		//noise = step( 1.0 - pow( specular, 2.0 ), noise );
		//noise *= 2.0;
		//noise *= specular * 5.0;
		//noise *= 1.0;
		noise *= ndoth;
		//specular += noise;
		diffuse += noise * 1.5;
		//specular = clamp( specular, 0.0, 1.0 );
		//gl_FragColor = vec4( vec3( noise ), 1.0 );
		//gl_FragColor = vec4( specular, 1.0 );
		//gl_FragColor = vec4( v_DiffuseColour, 1.0 );
		//gl_FragColor = vec4( noise, 1.0 );
		//gl_FragColor = vec4( vec3( ndoth ), 1.0 );
		//return;
	#endif*/

	// Base Texture
#if defined(TIRES)
	// Colour the tyres
	highp vec4 fragColour = vec4(diffuseTexture.rgb + u_TyreColour * (0.5 * diffuseTexture.a), diffuseTexture.a);
#else
	highp vec4 fragColour = diffuseTexture;
#endif


	// Diffuse light
	fragColour.rgb *= diffuse;
#ifndef LIGHTS
	#if defined(SINGLE_SPEC) || defined(DOUBLE_SPEC) || defined(SPEC_TEXTURE)
		// Specular light
		#if defined(TIRES) || defined(ARMS) || defined(SPEC_MASK_IN_ALPHA)
			fragColour.rgb += specular*diffuseTexture.a*shadowMap; // Mask specular with alpha channel
		#else
			fragColour.rgb += (specular*2.0) * shadowMap;
		#endif
	#endif
#endif

#ifdef CUBE_MAP
	// Cubemap reflection
	#ifdef GLASS
		// Reduce ground reflection smoothly to a minimum of 0% when reflecting about half way downwards (fixes reflection on NASCAR side wings);
		float groundReflectionScale = clamp(1.0 + v_ReflectionWorldSpaceYAxis * 2.0, 0.0, 1.0);
		//Reflection 2.0: key features, 1:1 colour not multiplied, more reflection in bright, stronger reflection on glancing edge.
		lowp vec3 reflection = cubeHighRes * clamp(cubeHighRes * cubeHighRes, 0.9, 1.0) * (c_cubemultiplier * groundReflectionScale * float(gl_FrontFacing));
		fragColour.rgb += reflection * clamp(1.0 * (fresnelTerm + (pow(cubeHighRes.r, 2.5) * 0.75))* 1.0, 0.0, 1.0);//adding brightness to highlights
		fragColour.a += (pow(fresnelTerm.r, 5.0) * 0.95);
		fragColour.a += u_GlassFresnelFeedbackScale*cubeHighRes.r*float(gl_FrontFacing); //adding highlights to alpha to increase reflection strength in bright areas
	#else
		#if defined(TIRES) || defined(ARMS) || defined(SPEC_MASK_IN_ALPHA)
			// Mask reflection with alpha channel
			fragColour.rgb += (cubeHighRes * fresnelTerm) * (cubeHighRes.g * diffuseTexture.a);
		#else
			// Reduce ground reflection smoothly to a minumum of 25% when reflecting straight down
			float groundReflectionScale = clamp(1.0 + v_ReflectionWorldSpaceYAxis, 0.25, 1.0);
			highp vec3 reflectionpaint = cubeHighRes * clamp(cubeHighRes * cubeHighRes * cubeHighRes, 0.95, 1.0); //cubemap with very slight contrast multiplier, multiplied 
			highp vec3 paintReduction = (1.0 - diffuseTexture.rgb * (u_LightAmbientColour * 1.0));
			highp float diffuseLightingMultiplier = (1.5 + pow(clamp(fresnelTerm.r - 0.1, 0.0, 2.0), 1.0)*3.0);
			highp vec3 diffuseLightingReduction = clamp(diffuse.rgb * diffuseLightingMultiplier, 0.0, 1.0);
			highp float fresnelFeedback = cubeHighRes.r * cubeHighRes.g * cubeHighRes.b * u_FresnelFeedbackScale;
			highp vec3 fresnelEffect = clamp(1.0 * (fresnelTerm + fresnelFeedback) * 1.0, 0.0, 1.0);
			highp float contrastEffect = clamp(4.0 * pow(cubeHighRes.r+cubeHighRes.g+cubeHighRes.b, 4.0), u_ReflectionContrast, 1.0);
			fragColour.rgb += reflectionpaint*diffuseLightingReduction*paintReduction*fresnelEffect*contrastEffect*groundReflectionScale;
		#endif
	#endif
#endif //CUBE_MAP

#if defined(SINGLE_SPEC) || defined(DOUBLE_SPEC) || defined(SPEC_TEXTURE)
	#ifdef GLASS
		fragColour.a += specular.g;
	#endif
#endif

#ifdef DIRT //the dirt currently fights with the mask for texture unit 7, if you want to enable dirt, you should free another texture unit for it (e.g. merge fresnel ramp with spec ramp)
	//const float dirtFalloff = 0.1;
	//float dirtFactor = clamp((dirtTexture.a - u_DirtFactor) / dirtFalloff, 0.0, 1.0);
	//fragColour.rgb = mix(fragColour.rgb, dirtTexture.rgb * diffuse, dirtFactor);
#endif
	
#ifdef ROTOR_GLOW
	vec4 rotorGlow = texture2D(s_Texture6, v_TexCoord0);
	fragColour.rgb += clamp(rotorGlow.a-u_RotorGlow.x, 0.0, 1.0) * u_RotorGlow.y * rotorGlow.rgb;
#endif

#ifdef FOG
	#ifdef SUN_FOG
		fragColour.rgb = mix( fragColour.rgb, v_FogColour_Factor.rgb, v_FogColour_Factor.a );
	#else
		fragColour.rgb = mix( fragColour.rgb, u_FogColour, v_FogFactor );
	#endif
#endif

#ifdef ALPHA_MODULATE
	#ifdef SPEC_MASK_IN_ALPHA
		fragColour.a = u_AlphaModulate;
	#else
		fragColour.a *= u_AlphaModulate;
	#endif
#endif

#if defined(CAR_DISCARDWIPE_PASS_1) || defined(CAR_DISCARDWIPE_PASS_2)
	// Wipe edge glow
	highp float edge = 1.0 - clamp(abs(u_CarCrossfade - v_CrossfadeFactor) / 0.01, 0.0, 1.0);
	fragColour.rgb += 2.0 * fragColour.rgb * edge * edge;
	fragColour += edge;
#elif defined(CAR_WHEEL_CROSSFADE_PASS_1) || defined(CAR_WHEEL_CROSSFADE_PASS_2)
	// Radial wipe for wheels
	// Some highlighting along the wipe edge tightens up the graphics. 
	#if defined(TIRE_INNER_RADIUS_SCALE)
		highp float edge = step(abs(v_CrossfadeFactor - u_CarCrossfade), 0.06);
	#else
		highp float edge = step(abs(v_CrossfadeFactor - u_CarCrossfade), 0.03);
	#endif
	fragColour.rgb *= fragColour.rgb * 4.0 * edge + step(0.0, abs(v_CrossfadeFactor - u_CarCrossfade));
	fragColour.a = 1.0;
#elif defined(CAR_CROSSFADE_PASS_1)
	fragColour.rgb *= step(u_CarCrossfade, v_CrossfadeFactor);
#elif defined(CAR_CROSSFADE_PASS_2)
	fragColour.rgb *= step(1.0 - u_CarCrossfade, 1.0 - v_CrossfadeFactor);

	// Wipe edge glow
	highp float edge = 1.0 - clamp(abs(u_CarCrossfade - v_CrossfadeFactor) / 0.08, 0.0, 1.0);
	fragColour.rgb += 2.0 * fragColour.rgb * edge * edge;
#endif

#if defined(DIFFUSE_LIGHTING)
	gl_FragColor = vec4(diffuse, 1.0);
#else
	gl_FragColor = fragColour;
#endif

	//gl_FragColor.rgb = vec3( v_EdotN.x );
	//gl_FragColor.rgb = vec3( v_NdotH.x );
	//gl_FragColor.rgb = fresnelTerm;
	//gl_FragColor.rgb = vec3( specTerm );
	//gl_FragColor.rgb = v_DiffuseColour;

	//gl_FragColor.rgb = vec3( v_EdotN.x );
	//gl_FragColor.rgb = vec3( v_NdotH.x );
	//gl_FragColor.rgb = fresnelTerm;
	//gl_FragColor.rgb = vec3( specTerm );
	//gl_FragColor.rgb = v_DiffuseColour;
	//gl_FragColor.rgb = diffuseTexture.rgb; //just the car colour
	//gl_FragColor.rgb = fresnelTerm; //fresnel falloff
	//gl_FragColor.rgb = diffuse; //diffuse ligthign
	//gl_FragColor.rgb = diffuseTexture.rgb * diffuse; //diffuse ligthing over car colour
	//gl_FragColor.rgb = cubeHighRes; //diffuse ligthing

}


